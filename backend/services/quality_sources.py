"""Bounded local original-source inspection. No network/OCR/model calls."""
from hashlib import sha256
from pathlib import Path
import json
import re
import subprocess
import sys
from backend.services.golden_learning_slice import digest

EXTRACTOR_VERSION = "pypdf-native-question-region-v1"


def normalise(text):
    # Whitespace/layout wrappers only; preserve operators, powers and limits.
    value=re.sub(r"\n-\s*$","",str(text)).replace("−","-")
    value=value.replace("\\,","").replace("\\ ","").replace("$","")
    return re.sub(r"\s+","",value)


class NativePageReader:
    def __init__(self): self.cache={}
    def __call__(self,path,page,file_sha):
        key=(file_sha,page,EXTRACTOR_VERSION)
        if key in self.cache: return self.cache[key]
        code="import sys,json; from pypdf import PdfReader; r=PdfReader(sys.argv[1]); p=int(sys.argv[2]); assert not r.is_encrypted and len(r.pages)<=100 and 1<=p<=len(r.pages); t=r.pages[p-1].extract_text() or ''; assert len(t)<=100000; print(json.dumps({'text':t},ensure_ascii=True))"
        try:
            result=subprocess.run([sys.executable,"-c",code,str(path),str(page)],capture_output=True,
                timeout=15,text=True,encoding="utf-8",errors="replace")
            if result.returncode:
                value={"status":"ERROR","reason":"pdf_extraction_failed","error_type":"PdfSubprocessError"}
            else: value={"status":"PASS",**json.loads(result.stdout)}
        except (subprocess.TimeoutExpired,ValueError,OSError) as exc:
            value={"status":"ERROR","reason":"pdf_extraction_failed","error_type":type(exc).__name__}
        self.cache[key]=value
        return value


def material_descriptor(q, registry, roots):
    if str(q.id) in registry: return dict(registry[str(q.id)])
    source=(q.grading_config or {}).get("provenance",{}).get("source",{})
    citation=source.get("citation","")
    # Paths embedded in old citations, never download URLs or search user files.
    match=re.search(r"([A-Za-z]:[/\\][^；;\r\n`（]+?\.pdf)",citation)
    path=Path(match.group(1)) if match else None
    relative=re.search(r"个人复习原卷[/\\]([^；;\r\n`（]+?\.pdf)",citation)
    if path is None and relative:
        literal=Path(relative.group(1).replace("\\","/"))
        matches=[root/literal for root in roots if root.name=="个人复习原卷" and (root/literal).is_file()]
        if len(matches)==1: path=matches[0]
    yearly=re.search(r"((?:数学|数学二|408)[/\\]\d{4}[/\\][^；;\r\n`（]+?\.pdf)",citation)
    if path is None and yearly:
        literal=Path(yearly.group(1).replace("\\","/"))
        matches=[root/literal for root in roots if (root/literal).is_file()]
        if len(matches)==1: path=matches[0]
    sha_match=re.search(r"SHA256\s*[:：]\s*([a-fA-F0-9]{64})",citation)
    if path is None:
        year=str(source.get("year") or "")
        candidates=[p for root in roots if root.is_dir() for p in root.rglob("*.pdf")
            if year and year in p.name and ((source.get("subject") in {"数学二","math2"} and ("数学二" in p.name or "数学二" in str(p.parent)))
                or source.get("subject")=="408" and "408" in str(p))]
        if len(candidates)==1: path=candidates[0]
        elif sha_match:
            matched=[]
            for p in sorted(candidates):
                if p.stat().st_size<=64*1024*1024:
                    with p.open("rb") as stream:
                        if __import__("hashlib").file_digest(stream,"sha256").hexdigest()==sha_match.group(1).lower():
                            matched.append(p)
            if matched: path=matched[0]  # identical declared bytes, not a guessed edition
    page_match=re.search(r"(?:原卷页[：:]|第\s*)\[?(\d{1,3})",citation)
    return {"path":str(path) if path else None,"page":int(page_match.group(1)) if page_match else None,
            "expected_sha256":sha_match.group(1).lower() if sha_match else None,"question_number":source.get("question_number"),"locator_origin":"existing_citation_or_unique_local_filename"}


def inspect_source(q,descriptor,reader):
    path=Path(descriptor["path"]) if descriptor.get("path") else None
    if path is None or not path.is_file():
        return {"status":"UNKNOWN","reason":"SOURCE_UNVERIFIED","material_accessible":False,"descriptor":descriptor}
    if path.suffix.lower()!=".pdf":
        return {"status":"UNKNOWN","reason":"source_extension_not_supported","material_accessible":True,"descriptor":descriptor}
    if path.stat().st_size > 64*1024*1024:
        return {"status":"UNKNOWN","reason":"source_size_limit","material_accessible":True,"descriptor":descriptor}
    with path.open("rb") as stream:
        actual_sha=__import__("hashlib").file_digest(stream,"sha256").hexdigest()
    base={"material_accessible":True,"file_path":str(path.resolve()),"source_file_sha256":actual_sha,
        "expected_source_file_sha256":descriptor.get("expected_sha256"),"page":descriptor.get("page"),
        "question_number":descriptor.get("question_number"),"extractor_version":EXTRACTOR_VERSION,
        "source_identity_assurance":"local_paper_claim_not_official_authentication","coverage":[]}
    if descriptor.get("expected_sha256") and actual_sha != descriptor["expected_sha256"]:
        return {**base,"status":"UNKNOWN","reason":"source_material_version_changed"}
    declaration=(q.grading_config or {}).get("provenance",{}).get("source",{})
    years=set(re.findall(r"(?<!\d)(20\d{2})(?!\d)",path.name))
    if declaration.get("year") and len(years)==1 and str(declaration["year"]) not in years:
        return {**base,"status":"FAIL","reason":"source_paper_year_conflict","filename_years":sorted(years)}
    if declaration.get("year") and len(years)>1 and str(declaration["year"]) not in years:
        return {**base,"status":"UNKNOWN","reason":"multi_year_material_needs_page_identity","filename_years":sorted(years)}
    if (declaration.get("question_number") and descriptor.get("question_number")
            and declaration["question_number"]!=descriptor["question_number"]):
        return {**base,"status":"FAIL","reason":"source_question_number_conflict"}
    name=path.name.lower()
    if (declaration.get("subject") in {"math2","数学二"} and "408" in name or
            declaration.get("subject")=="408" and ("math2" in name or "数学二" in name)):
        return {**base,"status":"FAIL","reason":"source_paper_subject_conflict"}
    base["filename_identity_checked"]={"declared_year":declaration.get("year"),"filename_years":sorted(years),
        "scope":"filename/record conflict check, not official provenance proof"}
    # Reuse only an already approved, versioned source correction as a partial
    # observation. It does not certify the other stem/options or human trust.
    partial=[]
    for observation in descriptor.get("partial_observations",[]):
        field=observation.get("field")
        if field != "options.C" or not isinstance(q.options,dict): continue
        context={"stem":q.stem,"question_type":q.question_type,"kp_id":str(q.kp_id),
                 "options":{k:v for k,v in q.options.items() if k!="C"}}
        if digest(context) != observation.get("context_sha256"): continue
        expected,actual=observation["value"],q.options.get("C")
        matches=normalise(expected)==normalise(actual)
        partial.append({"field":field,"status":"PASS" if matches else "FAIL",
            "evidence_kind":"prior_versioned_correction_not_fresh_extraction", "expected":expected,"actual":actual})
        if not matches:
            return {**base,"status":"FAIL","reason":"source_field_difference","location":"options.C",
                "partial_checks":partial,"full_concordance_verified":False}
    base["partial_checks"]=partial
    if not descriptor.get("page") or not descriptor.get("question_number"):
        return {**base,"status":"UNKNOWN","reason":"source_page_or_question_locator_missing"}
    extracted=reader(path,descriptor["page"],actual_sha)
    if extracted["status"]=="ERROR": return {**base,**extracted}
    text=extracted.get("text","")
    if len(text.strip())<30 or any(c=="�" or "\ue000"<=c<="\uf8ff" for c in text):
        return {**base,"status":"UNKNOWN","reason":"scan_or_unreliable_native_glyphs","native_chars":len(text),"paid_ocr_executed":False}
    # Full comparison requires a uniquely delimited question region. Searching
    # the whole PDF for a convenient substring could match a solution or Q12.
    number=descriptor["question_number"]
    marks=list(re.finditer(r"(?m)^\s*(\d{1,2})\s*[.．、)]",text))
    selected=[(i,m) for i,m in enumerate(marks) if int(m.group(1))==number]
    if len(selected)!=1:
        return {**base,"status":"UNKNOWN","reason":"native_question_region_not_unique","native_page_text_sha256":sha256(text.encode()).hexdigest()}
    i,match=selected[0]
    end=marks[i+1].start() if i+1<len(marks) else len(text)
    region=text[match.end():end]
    base["native_question_region_sha256"]=sha256(region.encode()).hexdigest()
    option_marks=list(re.finditer(r"(?:^|\n)\s*([A-Z])[.．、)]\s*",region))
    if q.question_type=="single_choice":
        if len(option_marks)!=len(q.options or {}) or {m.group(1) for m in option_marks}!=set(q.options or {}):
            return {**base,"status":"UNKNOWN","reason":"native_options_cannot_be_reliably_segmented"}
        stem=region[:option_marks[0].start()].strip()
        refs={m.group(1):region[m.end():option_marks[j+1].start() if j+1<len(option_marks) else len(region)].strip()
            for j,m in enumerate(option_marks)}
        # Different representation/paraphrase is not called a definite math
        # error. Exact equality is the deliberately narrow automatic PASS.
        matches=normalise(stem)==normalise(q.stem) and all(normalise(refs[k])==normalise(q.options[k]) for k in refs)
    else:
        matches=normalise(region)==normalise(q.stem)
    if not matches:
        return {**base,"status":"UNKNOWN","reason":"native_representation_or_transcription_needs_comparison",
                "candidate_region":region,"full_concordance_verified":False,
                "teaching_field_checks": {"stem": compare_teaching_field(q.stem, stem if q.question_type=="single_choice" else region),
                    **({"options."+k: compare_teaching_field(q.options[k], refs[k]) for k in refs}
                       if q.question_type=="single_choice" else {})}}
    return {**base,"status":"PASS","reason":"exact_native_question_region_match",
        "coverage":["stem","all_options"] if q.question_type=="single_choice" else ["stem"],
        "full_concordance_verified":True,"math_semantics_from_extraction_inferred":False}


def compare_teaching_field(stored, original):
    """Bounded field comparison, NOT universal statement equivalence.

    Accept only typography or exact constant equivalence. A natural-language
    paraphrase/unsupported formula remains UNKNOWN, rather than assumed safe.
    """
    from backend.services.constant_expression import compare_constant_expressions
    def typography(value):
        value = normalise(str(value)).translate(str.maketrans({"，": ",", "。": ".", "；": ";", "：": ":", "（": "(", "）": ")"}))
        return value.rstrip(".")
    a, b = typography(stored), typography(original)
    if a == b:
        return {"status": "PASS", "reason": "typographic_equivalence_only"}
    verdict = compare_constant_expressions(str(stored), str(original))
    if verdict != "unknown":
        return {"status": "PASS" if verdict == "right" else "FAIL",
                "reason": "exact_constant_equivalence" if verdict == "right" else "material_constant_difference"}
    # Dropping a sign from an otherwise identical field is not punctuation.
    if b.replace("-", "") == a and b.count("-") > a.count("-"):
        return {"status": "FAIL", "reason": "missing_negative_sign"}
    if "\\int" in b and "\\int" in a and re.search(r"\\int\s*[_^]", b) and not re.search(r"\\int\s*[_^]", a):
        return {"status": "FAIL", "reason": "missing_integral_bounds"}
    return {"status": "UNKNOWN", "reason": "semantic_equivalence_outside_bounded_scope"}
