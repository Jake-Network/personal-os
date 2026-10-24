export const PROVIDERS = [
  { key: 'chatgpt_plan', label: 'ChatGPT 구독 (기본)', note: 'ChatGPT 요금제 사용량으로 답합니다. 별도 API 요금이 없습니다.' },
  { key: 'openai_api_key', label: 'OpenAI API 키', note: '서버에 설정한 API 키로 OpenAI API 계정에 요금이 청구됩니다. 직접 고를 때만 사용합니다.' },
  { key: 'codex_app_server', label: 'Codex 앱 서버', note: '아직 지원하지 않습니다.' },
];

export const OUTCOME: Record<string, string> = {
  completed: '완료',
  incomplete: '미완료',
  failed: '실패',
  quota_exceeded: '한도 초과',
  auth_error: '인증 오류',
  blocked: '설정 변경으로 중지',
  cancelled: '사용자 중지',
};

export const CALLBACK_ERROR: Record<string, string> = {
  access_denied: 'ChatGPT 로그인 동의가 취소되었습니다.',
  invalid_grant: '인증 코드가 만료되었습니다. 다시 시도하세요.',
};

export const PROVIDER_LABEL: Record<string, string> = Object.fromEntries(PROVIDERS.map(p => [p.key, p.label.replace(' (기본)', '')]));
