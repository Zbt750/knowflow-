"""FSRS question memory + tempered BKT skill estimates, independent of graduation.

Projection is replayed from immutable attempts. It never writes mastery/graduation.
Question versions are distinct memory objects; variants never inherit a card.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from fsrs import Card, Rating, Scheduler

ALGORITHM_VERSION = 'fsrs6.3.2-bkt-tempered-v2'
FSRS = Scheduler(enable_fuzzing=False, desired_retention=0.9)


@dataclass(frozen=True)
class Observation:
    attempt_id: str
    question_id: str
    version_id: str
    kp_id: str
    at: datetime
    result: str
    reliable: bool = True
    assisted: bool = False
    error_kind: str = 'unclassified'
    rating: str | None = None


@dataclass
class Skill:
    probability: float = 0.2
    right: int = 0
    wrong: int = 0
    skipped: int = 0
    unknown: int = 0
    last_at: datetime | None = None
    last_new_at: datetime | None = None
    questions: set = field(default_factory=set)
    days: set = field(default_factory=set)

    @property
    def stage(self):
        count = self.right + self.wrong
        if not count:
            return 'unlearned'
        if (self.probability >= .85 and count >= 10
                and len(self.questions) >= 4 and len(self.days) >= 3):
            return 'stable'
        return 'basic' if self.probability >= .6 and count >= 4 else 'learning'


@dataclass
class Projection:
    cards: dict = field(default_factory=dict)
    skills: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)


def replay(observations, now):
    """Deterministic state reconstruction; duplicate receipts do not count twice."""
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    projection = Projection()
    seen = set()
    skill_opportunities = set()
    for o in sorted(observations, key=lambda o: (o.at, o.attempt_id)):
        if o.at.tzinfo is None:
            raise ValueError('timezone_required')
        if o.at > now or o.attempt_id in seen:
            continue
        seen.add(o.attempt_id)
        skill = projection.skills.setdefault(o.kp_id, Skill())
        # Exposure is a fact even if scoring is unknown; it is not mastery.
        if o.result == 'skipped':
            skill.skipped += 1
            continue
        skill.last_at = max(skill.last_at or o.at, o.at)
        if o.result not in {'right', 'wrong'} or not o.reliable or o.assisted:
            skill.unknown += 1
            # Ratings are not trust certificates. Reference/assisted responses
            # stay observations and cannot change the trusted memory queue.
            continue
        key = (o.question_id, o.version_id)
        first_question_review = key not in projection.cards
        review_at = o.at.astimezone(timezone.utc)
        card = projection.cards.get(key) or Card(card_id=len(projection.cards)+1, due=review_at)
        rating = {'again':Rating.Again,'hard':Rating.Hard,'good':Rating.Good}.get(o.rating)
        if rating is None:
            rating = Rating.Good if o.result == 'right' else Rating.Again
        card, _ = FSRS.review_card(card, rating,
                                   review_datetime=review_at)
        projection.cards[key] = card
        if first_question_review:
            skill.last_new_at=max(skill.last_new_at or o.at,o.at)
        if not o.reliable or o.assisted:
            continue
        if o.result == 'wrong':
            kind = o.error_kind if o.error_kind in {'concept', 'method', 'calculation', 'careless'} else 'unclassified'
            projection.errors[kind] = projection.errors.get(kind, 0) + 1
        # Recalling the same answer repeatedly today is not independent skill evidence.
        day = o.at.astimezone(timezone(timedelta(hours=8))).date()
        opportunity = (o.kp_id, o.question_id, day)
        if opportunity in skill_opportunities:
            continue
        skill_opportunities.add(opportunity)
        skill.questions.add(o.question_id)
        skill.days.add(day)
        correct = o.result == 'right'
        skill.right += int(correct)
        skill.wrong += int(not correct)
        # BKT emission: slip=.1, guess=.2; tempered likelihood reduces single-answer shocks.
        p = skill.probability
        learned = (.9 if correct else .1) ** .35
        unlearned = (.2 if correct else .8) ** .35
        posterior = p * learned / (p * learned + (1-p) * unlearned)
        skill.probability = posterior + (1-posterior) * .04
    return projection


@dataclass(frozen=True)
class Candidate:
    question_id: str
    version_id: str
    kp_id: str
    minutes: int
    variant_group: str | None = None


def allocate(candidates, projection, now, budget, *, per_node_new_limit=3):
    """Due queue first, then breadth/skill coverage. No fixed review/new ratio.

    Only caller-qualified candidates enter here. Overflow is explicit, never
    silently deletes already-confirmed work. Call only for a new daily plan.
    """
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    now = now.astimezone(timezone.utc)
    if type(budget) is not int or not 1 <= budget <= 240:
        raise ValueError('invalid_budget_minutes')
    pool = {}
    for c in candidates:
        if type(c.minutes) is not int or c.minutes <= 0:
            raise ValueError('invalid_question_minutes')
        if c.question_id in pool and pool[c.question_id] != c:
            raise ValueError('ambiguous_question_version')
        pool[c.question_id] = c
    due, new = [], []
    for c in pool.values():
        card = projection.cards.get((c.question_id, c.version_id))
        if card is not None:
            if card.due <= now:
                due.append(c)
        else:
            new.append(c)
    due.sort(key=lambda c: (FSRS.get_card_retrievability(
        projection.cards[(c.question_id,c.version_id)], current_datetime=now),
        projection.cards[(c.question_id,c.version_id)].due, c.question_id))
    # Dynamic coverage floor only when due debt would leave no room and a
    # topic has received no fresh practice for at least three days. Reserve
    # the actual cost of one such item, not a permanent new/review percentage.
    due_groups={c.variant_group for c in due if c.variant_group}
    coverage=[]
    for c in new:
        skill=projection.skills.get(c.kp_id,Skill())
        last=skill.last_new_at
        if (last is None or now-last>=timedelta(days=3)) and c.minutes<=budget and (
                not c.variant_group or c.variant_group not in due_groups):
            coverage.append(c)
    reserve=None
    if coverage and sum(c.minutes for c in due)>=budget-min(c.minutes for c in coverage):
        reserve=min(coverage,key=lambda c:(projection.skills.get(c.kp_id,Skill()).last_new_at
            or datetime.min.replace(tzinfo=timezone.utc),c.minutes,c.question_id))
    reserved_minutes=reserve.minutes if reserve else 0
    picked, used, groups, counts = [], 0, set(), {}
    for c in due:
        if used+c.minutes <= budget-reserved_minutes:
            picked.append((c, 'review')); used += c.minutes
            if c.variant_group: groups.add(c.variant_group)
    if reserve:
        picked.append((reserve,'new'));used+=reserve.minutes
        counts[reserve.kp_id]=1
        if reserve.variant_group:groups.add(reserve.variant_group)
        new.remove(reserve)
    def rank(c):
        skill = projection.skills.get(c.kp_id, Skill())
        last = skill.last_at
        elapsed = (now-last).total_seconds()/86400 if last else 9999
        # A one-day cooldown is a penalty, not permanent exclusion.
        cooled = elapsed < 2 if last else False
        return (cooled, counts.get(c.kp_id,0), skill.probability,
                -elapsed, c.kp_id, c.question_id)
    while new:
        new.sort(key=rank)
        c = new.pop(0)
        if counts.get(c.kp_id,0) >= per_node_new_limit:
            continue
        if c.variant_group and c.variant_group in groups:
            continue
        if used+c.minutes <= budget:
            picked.append((c,'new')); used += c.minutes
            counts[c.kp_id] = counts.get(c.kp_id,0)+1
            if c.variant_group: groups.add(c.variant_group)
    return {'items': picked, 'minutes': used,
            'due_total':len(due), 'due_remaining':len(due)-sum(k=='review' for _,k in picked),
            'new_coverage_reservation_minutes':reserved_minutes,
            'review_debt_minutes':sum(c.minutes for c in due)-sum(c.minutes for c,k in picked if k=='review'),
            'algorithm': ALGORITHM_VERSION}
