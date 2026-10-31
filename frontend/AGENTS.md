<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Personal OS — 프런트엔드 개발 지침

`frontend/`에 적용한다. [루트 지침](../AGENTS.md)의 제품·데이터·승인 원칙을 따른다. 위 Next.js 자동 생성 블록은 보존하고, 프런트엔드 코드를 바꾸기 전에 해당 주제의 설치된 Next.js 문서만 읽는다.

## 필요한 상세만 읽기

[상세 가이드](../docs/frontend-agent-guide.md)는 자동으로 전부 읽지 않는다. 변경할 동작에 해당하는 절만 확인한다.

| 작업 | 읽을 절 |
| --- | --- |
| 메뉴·라우트·화면 흐름 | [사용자 경험](../docs/frontend-agent-guide.md#navigation) |
| 폼·표·달력·문구·접근성 | [화면 패턴](../docs/frontend-agent-guide.md#ui) |
| API·재시도·캐시 | [API 계약](../docs/frontend-agent-guide.md#api) |
| 금액·차트·날짜·Sheets | [재무와 시간대](../docs/frontend-agent-guide.md#finance) |
| 상담·실행·공유·문서·승인 | [상담 UI](../docs/frontend-agent-guide.md#advisor) |
| 영향별 테스트·브라우저 검증 | [검증](../docs/frontend-agent-guide.md#verification) |

## 구조와 공통 원칙

아래 소스 경로는 이 디렉터리 기준이다.

| 위치 | 책임 |
| --- | --- |
| `src/app/` | App Router 페이지·레이아웃·메타데이터. 업무 로직은 기능 모듈로 위임. |
| `src/features/` | 도메인별 UI·상태·API 어댑터. 기존 기능 모듈과 패턴을 먼저 찾는다. |
| `src/api-client/generated/`, `src/api-client/model/` | 백엔드 OpenAPI에서 Orval로 생성. 수작업 수정 금지. |
| `src/api-client/custom-client.ts` | 공용 HTTP·CSRF·세션 만료 처리. |
| `src/api-client/event-stream.ts`, `src/api-client/api-error.ts` | 공용 SSE 전송·오류 정규화. |
| `src/components/`, `src/components/ui/` | 공용 UI·접근성·Markdown·달력. |
| `src/widgets/` | provider, 앱 셸, 내비게이션. |
| `src/lib/` | QueryClient, 한국어 라벨, `utils/format.ts`·`utils/zoned.ts`. |

- 한국어 UI와 기존 앱 셸을 사용한다. 현재 상태, 불확실성, 다음 행동을 보여준다. 결측·공유 제외·오래됨·부분 성공·실패를 서로 구별한다.
- 기존 TypeScript 타입, `@/` import, Tailwind/shadcn, React Hook Form/Zod 패턴을 따른다. 입력 폼은 `features/personal-data/hooks/use-schema-fields.ts`와 스키마 유틸리티를 재사용하고 필드 정의를 복제하지 않는다.
- 서버 상태는 TanStack Query, 일시적인 입력·열림 상태는 필요한 컴포넌트가 소유한다. 다른 대화로 상태가 섞이지 않게 한다. `'use client'`는 상호작용·브라우저 API가 필요한 경계에 둔다.
- `PageHeader`/`AreaLayout`, `Section`, `RecordSheet`, `EmptyState`, `QueryStatus`, `StatusBadge`/`QualityBadge`를 재사용한다. 삭제 확인은 범위를 설명하는 `useConfirm`을 사용한다.

## API·개인정보·표시

- 백엔드 OpenAPI가 계약의 원본이다. 생성 hooks와 query-key를 우선 사용하고 계약 변경 시 `generate-api`로 재생성한다. 변경한 데이터와 연결된 조회 캐시도 무효화한다.
- 동일 출처 `/api/*`, `/openapi.json`과 기존 전송 계층을 사용한다. 브라우저 코드·저장소·`NEXT_PUBLIC_*`에 OAuth 비밀·토큰·개인 원문을 넣지 않는다. 인증·CSRF 처리를 우회하지 않는다.
- 저장 여부가 불명확한 쓰기는 서버 상태부터 확인한다. 새 요청 ID로 무조건 재전송하거나 이전 계정 캐시를 재사용하지 않는다. 오류는 공용 `ApiError`·`errorMessage`로 표시한다.
- Decimal 문자열의 정밀도를 입력·저장까지 보존한다. 재무 계산은 백엔드 결과를 사용하고 `null`·실패를 0으로 바꾸지 않는다. 금액 포맷과 품질 표시는 기존 `format.ts`, `features/finance/presentation.ts`를 쓴다.
- 날짜만 있는 값과 시각을 구별한다. `TimezoneGate`가 설정한 앱 시간대와 기존 `format.ts`·`zoned.ts`를 사용한다. 브라우저 시간대를 가정하거나 ISO 문자열을 잘라 날짜를 만들지 않는다.
- 대시보드 조회에는 LLM이 필요 없다. 로컬 표시와 모델 공유는 별개이며 공유 정책은 서버가 검증한다. 승인·거절·기억 확인은 명시적인 사용자 동작으로 유지한다.

## 상담 실행의 경계

- `src/app/(main)/advisor/layout.tsx`의 `AdvisorWorkspace`와 `useWorkspace` 구조를 유지한다. 서버가 실행을 소유하며 화면 이동·구독 해제는 실행 취소가 아니다.
- 현재 SSE는 `/api/advisor/runs/{run_id}/events`의 `RunEvent`(`seq`, `revision`, `payload`)다. `status`·`progress`·`clarification`·`data_operations`도 처리하며 순번 기반 재연결과 답변 revision을 보호한다. `context`→`delta`→`done/error`만 있는 형태는 레거시 호환 경로다.
- 실행 생성과 확인 질문 응답은 별도 요청이다. 요청 ID·질문 ID·revision을 유지하고 명시적 중지 뒤 서버 상태를 확인한다. 검증 전 모델 초안을 확정 답변으로 표시하지 않는다.
- 공유 범위·문서·분석 옵션 변경 후 이전 전송 본문을 재사용하지 않는다. 미리보기와 답변 당시 스냅샷을 구별하고, 인용은 당시 문서 버전·페이지·발췌를 유지한다.
- 직접 요청한 CRUD의 저장 결과와 승인 대기 제안을 구별한다. 답변 실패 뒤에도 저장 성공은 보여준다. 자동 기록의 초기 설정은 꺼짐이며 새 대화는 저장된 `recording.default_enabled`를 따른다. 현재 선택을 요청별 `allow_data_recording`으로 전달한다.

## 검증과 유지

명령은 `frontend/`에서 실행한다. 변경 영향에 맞는 최소 검증부터 수행하며 상세 가이드에서 관련 회귀 테스트를 고른다. 프런트엔드 검증을 위해 개인 운영 DB를 초기화하지 않는다.

```bash
corepack yarn install --frozen-lockfile
corepack yarn audit --level moderate # 의존성 변경 시
corepack yarn generate-api # API 계약 변경 시; 실행 중인 백엔드 또는 OPENAPI_TARGET
corepack yarn lint
corepack yarn typecheck
corepack yarn test
corepack yarn build
corepack yarn e2e # 가짜 제공자 + 이름이 _e2e로 끝나는 폐기용 DB; 시작 시 초기화
```

화면 변경은 가능한 환경에서 데스크톱·좁은 화면과 관련 빈 상태·실패·접근성을 확인한다. 정적 검사·단위 테스트·브라우저 스모크·실제 외부 연동의 결과를 구별한다. 문서만 바꾸면 링크·명령·코드 일치와 diff를 확인한다. 공통 원칙은 루트, 핵심 프런트 지침은 이 파일, 상세는 작업별 가이드에서 관리하고 바뀐 설명을 함께 갱신한다.
