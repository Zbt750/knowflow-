/** Presentation punctuation only; preserve the recommendation's content. */
export function recommendationSentence(text:string):string {
 const value=text.trim();
 if(!value || /[！？!?]$/u.test(value))return value;
 return value.replace(/[。.]+$/u,'')+'。';
}
