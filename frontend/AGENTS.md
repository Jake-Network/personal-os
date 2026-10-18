<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Personal OS — 프런트엔드 개발 지침

이 문서는 `frontend/` 전체에 적용하며 [루트 AGENTS.md](../AGENTS.md)의 제품·데이터·승인 원칙을 보완한다. 공통 정책은 루트에서 관리하고, 여기에는 화면과 프런트엔드 구현 지침을 둔다. 구조·계약·검증 방법을 변경하면 관련 지침도 함께 갱신한다. 위 Next.js 자동 생성 블록은 보존한다.

## 사용자 경험의 목적

사용자가 자신의 자산·재무·커리어·일정·목표를 파악하고, 개인 데이터에 근거해 상담하고, 선택과 실행 결과를 확인하도록 만든다. 각 화면에는 현재 상태, 근거와 불확실성, 다음 행동이 드러나야 한다.

- 대시보드는 중요한 상태와 다가오는 일정을 빠르게 파악하는 곳이다. 요약에서 관련 데이터 관리·상담으로 이어지게 한다. 대시보드 조회를 위해 LLM을 호출하지 않는다.
- 상담은 질문·답변뿐 아니라 공유 범위, 사용한 데이터, 인용 근거와 승인할 제안을 함께 확인하는 작업 공간이다. 답변과 근거 패널의 연결을 유지한다.
- 재무 화면은 통화·기준일·출처·기록 범위를 보여주고, 커리어·일정·목표 화면은 진행 상태와 다음 행동을 보여준다. 각 도메인의 의미를 무시한 범용 표만으로 모든 경험을 대체하지 않는다.
- 기억·의사결정 기록은 사용자의 확인과 회고를 돕는다. 모델이 제안한 기억, 확정된 기억, 예상 결과와 실제 결과를 구별한다.
- 한국어 UI와 기존 앱 셸을 기본으로 한다. 좁은 화면에서도 상담 목록, 입력창과 근거를 사용할 수 있게 한다. 키보드 탐색, 입력 라벨, 포커스, dialog/sheet 제목과 아이콘 버튼의 접근 가능한 이름을 챙긴다.

## 구조와 책임

아래 경로는 이 디렉터리 기준이다. 해당 버전의 Next.js 동작은 위 자동 생성 지침에 따라 설치된 로컬 문서에서 확인한다.

| 위치 | 책임 |
| --- | --- |
| `src/app/` | App Router 페이지·레이아웃·메타데이터. 도메인 로직은 기능 모듈로 위임한다. |
| `src/features/` | `advisor`, `dashboard`, `finance`, `holdings`, `documents`, `personal-data`, `memory`, `career`, `reviews`, `security`, `approvals`, `settings` 등 기능별 UI·상태·어댑터. |
| `src/api-client/generated/`, `src/api-client/model/` | 백엔드 OpenAPI에서 Orval로 생성하는 함수·Query hooks·타입. 직접 수정하지 않는다. |
| `src/api-client/custom-client.ts` | 일반 HTTP 요청의 공용 axios mutator. |
| `src/api-client/event-stream.ts`, `src/api-client/api-error.ts` | SSE 전송과 공통 오류 정규화. |
| `src/components/`, `src/components/ui/` | 공용 UI, Markdown 렌더링, 알림과 shadcn/Radix 기반 기본 요소. |
| `src/widgets/` | provider, 앱 셸, 사이드바와 내비게이션. |
| `src/lib/` | QueryClient 설정, 한국어 라벨과 공용 포맷 유틸리티. |

- 기존 TypeScript 타입과 `@/` import, Tailwind·shadcn, React Hook Form/Zod 패턴을 따른다. 중복 UI, 병렬 상태 관리 체계나 의존성을 추가하기 전에 기존 구현을 찾는다.
- 서버 상태는 TanStack Query로 관리하고 대화 입력·패널 열림 등 일시적인 UI 상태는 필요한 컴포넌트에 둔다. 브라우저 상태가 다른 대화나 새 상담에 섞이지 않게 한다.
- 상호작용과 브라우저 API가 필요한 경계에 `'use client'`를 둔다. 루트 전체를 불필요하게 클라이언트로 바꾸지 않는다.

## API 계약과 캐시

- 백엔드 OpenAPI를 계약의 원본으로 사용한다. 기존 생성 hooks를 우선 재사용하고, 수동 어댑터가 필요한 경로는 도메인의 `api.ts`와 공용 전송 계층을 따른다. 수동 타입도 백엔드 계약과 함께 확인한다.
- `src/features/personal-data/hooks/use-schema-fields.ts`와 `utils/schema-fields.ts`의 스키마 기반 입력 폼을 유지한다. 같은 필드 정의를 별도로 복제하지 않는다.
- 요청은 동일 출처의 `/api/*`, `/openapi.json`을 사용한다. `next.config.ts`의 rewrite와 서버 측 `SERVER_DOMAIN` 설정을 따른다. 브라우저 코드에 백엔드 절대 주소·OAuth 비밀·토큰을 넣지 않는다.
- 변경 후에는 영향을 받는 조회를 무효화한다. 생성된 query-key 함수를 재사용하고, 수동 API는 기존 키를 확인한다. 제안 승인 후 작업·일정·목표, 데이터 변경 후 대시보드, 연결 변경 후 포트폴리오 등의 갱신 범위를 검토한다.
- 재시도·폴링은 비용과 부작용을 고려한다. 개인 데이터나 Sheets 쓰기를 실패 여부가 불명확한 상태에서 새 요청 ID로 반복하지 않는다. 연결 계정이 바뀌면 이전 계정의 캐시를 현재 데이터처럼 표시하지 않는다.
- 오류는 공용 `ApiError`, `errorMessage`, 알림 패턴을 사용한다. 인증 만료, 공유 제한, 입력 오류, 서버 연결 실패와 부분 성공을 구별하고 필요한 다음 행동을 제시한다.

## 재무 표시와 입력

- 금액·수량·환율의 API Decimal 문자열을 입력·저장까지 보존한다. 화면 좌표·포맷을 위한 변환과 재무 계산을 구분한다. 순자산·런웨이 등 업무 계산은 백엔드 결과를 사용한다.
- `src/features/finance/presentation.ts`, `src/lib/utils/format.ts`, `src/lib/labels.ts`의 해당 화면용 규칙을 재사용한다. 원본 정밀도가 필요한 금액을 표시 편의상 반올림한 값으로 저장하지 않는다.
- `null`, 빈 값, 수집 실패를 `0`으로 바꾸지 않는다. 실제 0은 0으로 표시하고, 알 수 없는 값은 확인 필요·미기록 상태로 표시한다. 부분 합계와 오래된 값에는 관련 표시를 유지한다.
- 월별 차트는 누락 월·알 수 없는 값 사이의 선을 끊는다. 누락 기간을 연속 추세나 수익률로 표현하지 않는다. 과거 기록 정정은 기존 revision과의 관계를 보여준다.
- 로컬 DB를 재무 원본으로 사용한다. Google 시세 연결이 없어도 입력을 허용한다. Google 전송에는 티커·통화쌍·생성 시세 수식만 포함한다. 로컬 저장·시세 대기·시세 실패를 구분하며 안정적인 position/request ID와 `expected_version`을 유지한다.
- 날짜만 있는 값과 시각이 있는 값을 구분하고 기존 포맷 함수를 사용한다. 브라우저 시간대가 백엔드의 `PERSONAL_OS_TIMEZONE`과 같다고 가정하지 않는다. 일정 기간과 기준 시각을 오해할 수 있으면 표시를 보완한다.

## 상담·문서·승인 UI

- `src/app/(main)/advisor/layout.tsx`가 `AdvisorWorkspace`를 유지하는 구조를 보호한다. `/advisor`에서 `/advisor/[id]`로 이동할 때 새 답변 스트림이 재마운트로 사라지지 않아야 한다.
- SSE의 `context` → `delta` → `done` 또는 `error`, 사용자 중단과 연결 종료를 구분한다. 전송 중 중복 제출, 취소 후 늦게 도착한 이벤트, 대화 전환 시 상태 혼입을 검토한다.
- `next.config.ts`의 압축 비활성화와 긴 proxy timeout은 스트리밍을 위한 설정이다. 변경 시 답변이 완료 전부터 표시되는지 실제로 확인한다.
- Context Inspector의 전송 미리보기와 답변 당시 스냅샷을 구별한다. 공유 토글·문서 선택과 요청 payload를 일치시키며 서버의 공유 정책을 UI만으로 대체하지 않는다.
- 문서 인용은 서버가 제공한 ref·버전·페이지·발췌로 연결한다. 과거 근거를 최신 파일로 대체하지 않는다. Markdown·외부 링크·업로드 내용은 신뢰하지 않는 입력으로 취급하며 임의 HTML 실행 경로를 열지 않는다.
- 문서의 업로드·처리 중·검색 가능·실패, 활성 버전과 새 버전 상태를 구별한다. 파일 교체·재시도·공유 해제 후 관련 목록과 근거 표시를 갱신한다.
- 승인·거절과 기억 확인은 명시적 사용자 동작이어야 한다. 생성된 제안을 자동 승인하거나 성공 전 적용된 것으로 표시하지 않는다. UI에서 중복 클릭을 막고 서버의 경합·검증 오류도 처리한다.
- 삭제할 때 문서 원본, 과거 근거, 대화 텍스트의 삭제 범위를 분명히 설명한다. UI에서 제거된 항목이 캐시나 열려 있는 근거 패널에 남는지도 확인한다.

## 검증과 문서 유지

아래 명령은 `frontend/`에서 실행한다. API 재생성은 실행 중인 백엔드의 `/openapi.json` 또는 `OPENAPI_TARGET`으로 지정한 저장된 스키마를 사용한다. 프런트엔드 검증만을 위해 개인 운영 DB를 초기화하지 않는다.

```bash
corepack yarn install --frozen-lockfile
corepack yarn generate-api # API 계약 변경 시
corepack yarn lint
corepack yarn typecheck
corepack yarn test
corepack yarn build
```

- 최소 검증은 변경 영향에 맞춰 선택한다. SSE는 `src/api-client/event-stream.test.ts`, 오류는 `src/api-client/api-error.test.ts`, 재무 표시는 `src/features/finance/presentation.test.ts`, Sheets 입력은 `src/features/holdings/api.test.ts`, 스키마 폼은 `src/features/personal-data/utils/schema-fields.test.ts`를 출발점으로 삼는다.
- 화면을 변경했다면 가능한 환경에서 데스크톱·좁은 화면, 데이터 없음·로딩·실패, 긴 한국어 제목·큰 금액·중복 제출 등 관련 상태를 확인한다. 정적 검사와 단위 테스트 통과를 브라우저 검증으로 보고하지 않는다.
- 실시간 LLM·OAuth·Google Sheets 검증과 모킹된 테스트를 구별한다. 문서만 수정한 경우에는 링크·경로·명령과 코드의 일치 및 diff를 확인한다.
- 루트에는 공통 제품·보안·데이터 원칙을, 이 파일에는 프런트엔드 구조·화면 동작·실행 방법을 관리한다. 라우팅·공용 클라이언트·API 생성·주요 UX 변경 시 두 문서의 관련 항목을 함께 확인하고 오래된 지침을 수정한다.
