import { calculateContractDuration } from './contractDuration';

test.each([
  ['2027-05-03', '2028-04-07', { months: 11, days: 4, totalDays: 340 }],
  ['2024-01-31', '2024-02-29', { months: 1, days: 0, totalDays: 29 }],
  ['2023-01-31', '2023-03-01', { months: 1, days: 1, totalDays: 29 }],
  ['2024-02-29', '2025-02-28', { months: 12, days: 0, totalDays: 365 }],
  ['2026-03-07', '2026-03-10', { months: 0, days: 3, totalDays: 3 }],
  ['2026-09-20', '2026-09-20', { months: 0, days: 0, totalDays: 0 }],
])('calculates elapsed calendar duration from %s to %s', (start, end, expected) => {
  expect(calculateContractDuration(start, end)).toEqual(expected);
});
test.each([
  [null, '2027-05-03'], ['2027-05-03', undefined], ['', '2027-05-03'],
  ['2027-05-04', '2027-05-03'], ['2027-02-29', '2027-05-03'],
  ['2027-04-31', '2027-05-03'], ['3 May 2027', '2028-04-07'],
  ['2027-05-03T00:00:00Z', '2028-04-07'],
])('omits unavailable or invalid date pairs: %s / %s', (start, end) => {
  expect(calculateContractDuration(start, end)).toBeNull();
});
