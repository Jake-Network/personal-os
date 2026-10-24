/** Workout durations are stored as whole seconds, never rounded to minutes. */
export function durationInput(seconds: number): string {
  return `${Math.floor(seconds / 3600)}:${Math.floor((seconds % 3600) / 60)}:${seconds % 60}`;
}

export function durationSeconds(value: string): number {
  const parts = value.split(':');
  if (parts.length !== 3 || parts.some(part => !/^\d*$/.test(part))) {
    throw new Error('운동 시간은 시간·분·초에 정수로 입력하세요.');
  }
  const [hours, minutes, seconds] = parts.map(Number);
  const total = hours * 3600 + minutes * 60 + seconds;
  if (minutes > 59 || seconds > 59 || !Number.isSafeInteger(total) || total <= 0) {
    throw new Error('운동 시간은 0초보다 크게, 분과 초는 0~59로 입력하세요.');
  }
  return total;
}

export function formatDuration(value: unknown): string {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) return '—';
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  return [hours ? `${hours}시간` : '', minutes ? `${minutes}분` : '', seconds || !value ? `${seconds}초` : ''].filter(Boolean).join(' ');
}
