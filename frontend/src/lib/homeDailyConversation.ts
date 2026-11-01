/** Homepage conversations follow the Shanghai calendar without deleting history. */
export function homeStudyDay(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const value = (type: string) => parts.find(p => p.type === type)!.value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}
export const homeDayKey = (day: string) => `naiwa:home-recommendation:day:v1:${day}`;
export const homeDayTitle = (day: string) => `首页学习 ${day}`;
