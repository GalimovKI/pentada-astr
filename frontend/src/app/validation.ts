import { QUERY_MAX_LENGTH } from "../api/client";

// Calendar-only validation, deliberately without Date or timezone conversion.
export function validDate(value: string): boolean {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  if (year < 1 || month < 1 || month > 12) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day >= 1 && day <= days[month - 1];
}

export function queryError(query: string): string | null {
  if (!query.trim()) return "Введите поисковый запрос.";
  // Python's max_length counts Unicode code points rather than UTF-16 units.
  if ([...query].length > QUERY_MAX_LENGTH)
    return `Запрос должен содержать не более ${QUERY_MAX_LENGTH} символов.`;
  return null;
}
