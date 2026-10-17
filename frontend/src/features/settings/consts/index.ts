export const PROVIDERS = [
  { key: 'chatgpt_plan', label: 'ChatGPT 구독 (기본)', note: 'ChatGPT 요금제 사용량으로 응답합니다. 별도 API 과금이 없습니다.' },
  { key: 'openai_api_key', label: 'OpenAI API Key', note: '서버 환경변수 OPENAI_API_KEY로 API 계정에 과금됩니다. 직접 선택할 때만 사용됩니다.' },
  { key: 'codex_app_server', label: 'Codex app-server', note: '아직 지원하지 않습니다.' },
];

export const OUTCOME: Record<string, string> = {
  completed: '완료',
  incomplete: '미완료',
  failed: '실패',
  quota_exceeded: '한도 초과',
  auth_error: '인증 오류',
};

export const CALLBACK_ERROR: Record<string, string> = {
  access_denied: 'ChatGPT 로그인 동의가 취소되었습니다.',
  invalid_grant: '인증 코드가 만료되었습니다. 다시 시도하세요.',
};
