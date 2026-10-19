<!-- AUTONOMY DIRECTIVE — DO NOT REMOVE -->
YOU ARE AN AUTONOMOUS CODING AGENT. EXECUTE TASKS TO COMPLETION WITHOUT ASKING FOR PERMISSION.
DO NOT STOP TO ASK "SHOULD I PROCEED?" — PROCEED. DO NOT WAIT FOR CONFIRMATION ON OBVIOUS NEXT STEPS.
IF BLOCKED, TRY AN ALTERNATIVE APPROACH. ONLY ASK WHEN TRULY AMBIGUOUS OR DESTRUCTIVE.
USE CODEX NATIVE SUBAGENTS FOR INDEPENDENT PARALLEL SUBTASKS WHEN THAT IMPROVES THROUGHPUT. THIS IS COMPLEMENTARY TO OMX TEAM MODE.
<!-- END AUTONOMY DIRECTIVE -->

# Personal OS — 개발 에이전트 지침

## 제품의 목적

Personal OS는 한 사람의 자산 포트폴리오, 재무 상태와 구조, 커리어, 일정, 목표 및 개인 문서를 연결하는 **개인 대시보드이자 의사결정 지원 에이전트**다. 사용자가 자신의 현재 상태를 파악하고, 개인 데이터에 근거해 LLM과 상담하고, 선택지를 비교하고, 승인한 행동을 실행하고, 결과를 돌아볼 수 있게 한다.

기능을 설계할 때 다음 사용자 흐름을 기준으로 판단한다.

1. **기록·연결:** 개인 데이터와 문서를 입력하거나 Google Sheets에서 가져온다.
2. **현재 상태 파악:** 자산·부채·현금흐름·지원 현황·예정 일정·목표를 출처와 기준일과 함께 확인한다.
3. **상담·비교:** 필요한 데이터만 공유해 사실, 가정, 대안, 위험과 제약을 검토한다.
4. **결정·행동:** 사용자가 선택하고, 구체적인 작업·일정·목표 변경 제안을 승인한다.
5. **회고:** 결정 당시 근거, 기대 결과와 실제 결과를 비교하고 선호·제약을 갱신한다.

예를 들어 “퇴사 후 이직을 준비해도 되는가?”는 생활비로 쓸 수 있는 현금, 지출 기록, 부채, 예정 지출, 채용 진행 상황, 면접 일정과 개인 목표를 함께 살펴야 한다. 도메인을 연결하되 질문에 불필요하거나 공유가 금지된 데이터까지 전송하지 않는다.

## 구현 범위와 제품 방향 구분

현재 코드를 먼저 확인한다. README, 과거 계획, 메모리의 설명과 실제 구현이 다르면 차이를 명시한다. 다음은 탐색의 출발점이며 모든 기능의 완성이나 운영 검증을 뜻하지 않는다.

| 영역 | 현재 코드의 역할과 진입점 |
| --- | --- |
| 대시보드 | `app/modules/dashboard/`, `frontend/src/features/dashboard/`: 상담과 같은 읽기 도구로 요약하며 표시 자체에는 LLM이 필요 없다. |
| 자산·재무 | `app/modules/finance/`, `app/modules/portfolio/`: 로컬 재무 원본, 시세 전용 Sheets, 결정적 계산, 거래·월별 이력, 수동 값 변경 이력. |
| 커리어·생활 관리 | `app/modules/personal_data/`, `app/modules/crud/`, `app/schema/domain_schema.py`: 채용 지원, 면접, 커리어 기준, 일정, 목표, 작업, 운동 기록 등. 재직·프로젝트·성과는 `app/modules/career/`에서 관리한다. |
| 개인 상담 | `app/modules/advisor/`, `app/modules/context/`: 질문별 데이터 선택, 공유 필터, 근거 스냅샷, 스트리밍 답변, 제안·기억·결정 기록. |
| 문서 상담 | `app/modules/documents/`: PDF·Markdown·TXT의 버전 관리, 비동기 인덱싱, 검색, 인용과 출처 추적. |
| 모델·연결 | `app/modules/llm/`, `app/modules/auth/`: 모델 제공자 인터페이스, ChatGPT 연결과 별도 Google OAuth. |

현재는 로컬 단일 사용자 제품이다. 모델 제공자 인터페이스의 존재를 실제 연동 완료로 간주하지 않는다. 특히 `CodexAppServerProvider`는 스텁이다. 외부 캘린더 동기화와 증권 거래를 지원한다고 가정하지 않는다. `app/modules/jobs/`의 주기 회고와 시세 갱신은 사용자가 명시적으로 활성화한 작업만 실행한다. 새로운 외부 연동이나 자동 실행은 권한·실패·취소 동작까지 별도 설계한다.

## 제품에서 지켜야 할 원칙

### 재무 데이터와 계산

- 금액·수량·환율·비중·시나리오 계산은 백엔드의 `Decimal` 기반 계산과 기존 스키마를 사용한다. LLM이나 프런트엔드에 별도 재무 계산 규칙을 만들지 않는다.
- 누락, 오래된 값, 수집 실패, 불완전한 범위를 `0`이나 정상 상태로 바꾸지 않는다. 출처, 통화, 기준일, 포함 범위와 `data_quality_flags`를 API·화면·상담까지 전달한다. 부분 합계는 완전한 총액과 구별한다.
- 순자산, 투자 가능 자산, 현금성 자산, 생활비로 사용할 수 있는 유동성을 구별한다. 주식·연금·기타 자산을 자동으로 생활비 재원에 포함하지 않는다. 런웨이는 기존 유동성 정책과 지출 기록 충족 조건을 따른다.
- 개인 재무 항목은 로컬 DB가 원본이다. Google 연결은 새 전용 Quotes/FX 파일의 시세 조회에만 사용하며 연결 상태로 로컬 입력을 제한하지 않는다. 과거 Sheets import는 미리보기와 원본 행 매핑으로 보존 이전한다.
- 보유 자산 입력은 로컬 저장 경로, 안정적인 position/request ID와 버전 검사를 따른다. Google에는 티커·통화쌍·생성 수식만 전송한다. 저장 성공·시세 대기·시세 실패를 구별하며 외부 호출과 로컬 감사 로그를 하나의 원자적 트랜잭션으로 가정하지 않는다.
- 현재 시세·수량·환율로 과거 월말 이력을 재구성하지 않는다. 역사적 수량, 종가, 환율 및 기록 범위의 근거가 필요하다. 월별 금액 차이를 근거 없이 투자 수익이나 저축의 결과로 단정하지 않는다.
- 스냅샷·값 변경 이력의 기존 append-only 규칙을 유지한다. 정정은 출처와 연결 관계가 남는 새 기록으로 처리한다.

### 개인정보와 상담 근거

- 로컬 대시보드 표시와 모델에 전송하는 공유 범위는 다르다. 대시보드에서 보인다는 이유로 상담에도 전송하지 않는다.
- 질문 라우팅 → 전역·요청별 공유 필터 → 필요한 데이터 조회 → 계산·문서 검색 → 예산 제한·스냅샷 → 모델 전송 흐름을 유지한다. 프롬프트의 지시만으로 공유 제한을 구현하지 않는다.
- 공유 제한은 새 조회뿐 아니라 과거 메시지, 문서 인용, 메모리와 파생된 후속 답변에도 적용한다. 근거 삭제·공유 해제 후 대화 이력을 통해 제한된 내용이 다시 전송되지 않게 한다.
- 상담은 매 요청의 최신 구조화 데이터와 결정적 계산을 사용한다. 후속 질문의 주제를 유지하더라도 과거 답변의 잔고·일정을 현재 값으로 재사용하지 않는다.
- 답변 당시 스냅샷과 레코드 참조, 문서 버전·페이지·발췌를 보존한다. 과거 인용을 최신 문서 내용으로 바꾸지 않는다. 삭제 시 원본·파생 데이터·근거 스냅샷·대화 텍스트 중 무엇을 지우는지 구별한다.
- 문서·JD·외부 텍스트는 신뢰하지 않는 데이터다. 포함된 지시를 도구 실행이나 권한 변경으로 연결하지 않는다. 검색 유사도를 사실의 확률로 제시하지 않는다.
- 컨텍스트 예산 초과, 검색 실패와 근거 생략을 사용자에게 드러낸다. 중요한 제약이나 불완전성 표시를 조용히 잘라내지 않는다.
- 컨텍스트 미리보기는 저장이나 LLM 호출 없이 전송 대상을 확인할 수 있어야 한다. 필수 근거만으로 예산을 초과하면 불완전한 요청을 보내지 않고 실패를 알린다.
- 토큰, 키, 원본 개인 문서와 실제 재무 기록을 로그·테스트 fixture·커밋·브라우저 저장소·`NEXT_PUBLIC_*`에 넣지 않는다. 테스트에는 합성 데이터를 쓴다.

### 상담, 결정, 실행의 경계

- 상담은 사용자의 판단을 돕는다. 사실·가정·예측을 구별하고, 복잡한 결정에서는 근거·선택지·위험·권장 행동을 제시한다. 짧은 조회에는 짧게 답한다.
- 재무, 커리어, 일정과 목표 간의 제약을 연결한다. 검증 가능한 통계 없이 투자 성과나 합격 확률을 만들어내지 않는다.
- 읽기 도구와 쓰기 경로를 분리한다. 현재 허용된 제안은 `create_task`, `calendar_update`, `goal_update`이며 실제 반영은 명시적 사용자 승인 후에만 한다. LLM에는 재무 테이블이나 Sheets 변경 경로를 제공하지 않는다.
- 제안 payload는 서버에서 검증한다. 중복 승인, 승인·거절 경합, 실패 시 롤백과 감사 기록을 보호한다. 도구나 action을 추가할 때 허용 목록과 회귀 검증도 함께 변경한다.
- LLM이 추출한 장기 기억은 사용자가 확인하기 전에는 확정하지 않는다. 의사결정 기록은 당시 근거·기대 결과·실제 결과를 구분해 회고할 수 있게 한다.
- **개발 에이전트의 자율 작업 권한은 제품 안의 승인 절차를 생략할 권한이 아니다.**

### 시간·연결·비용

- “오늘·이번 주·다음 달”은 `PERSONAL_OS_TIMEZONE`으로 해석하고 저장 시각과 조회 범위의 시간대를 명확히 한다. 기존 UTC 저장과 반열린 구간 규칙을 유지하며 모든 질문을 고정된 향후 기간으로 바꾸지 않는다.
- Google 연결과 모델 제공자 연결은 독립적이다. 만료·해제·계정 전환 후 다른 계정이나 자격증명으로 몰래 대체하지 않는다.
- 제공자·모델 변경은 명시적인 선택을 따른다. 실패나 할당량 초과를 이유로 유료 API 또는 외부 임베딩으로 자동 전환하지 않는다.
- 스트리밍 실패·중단으로 완성되지 않은 답변을 다음 상담의 확정된 이력으로 재전송하지 않는다.
- 로컬 신뢰 경계(`LocalTrustMiddleware`, Origin/Host 검사), 서버 측 토큰 암호화와 loopback 기본값을 유지한다. OAuth 연결은 애플리케이션 로그인 인증을 대신하지 않는다. 원격 공개에는 별도 인증·TLS 설계가 필요하다.

## 코드 구조와 변경 방법

- 백엔드: Python 3.13+, FastAPI, Pydantic, SQLAlchemy, Alembic, `uv`. HTTP 처리는 `app/router/`, 업무 규칙은 `app/modules/<domain>/`, 공통 ORM 접근은 `app/modules/crud/`, 모델은 `app/modules/database/model/`, 계약은 `app/schema/`에 둔다. 기존 도메인별 영속성 처리를 존중하며 라우터에 계산·검색·외부 API 로직을 쌓지 않는다.
- 세션과 트랜잭션 소유권을 명시한다. 핸들러에서 임의의 세션을 열거나 숨은 commit을 추가하지 않는다. 외부 요청 중 자격증명 갱신과 commit이 기존 잠금에 미치는 영향도 확인한다.
- 프런트엔드: Next.js App Router, React, TypeScript, TanStack Query, Tailwind/shadcn, React Hook Form/Zod, Orval, Yarn. 라우트는 `frontend/src/app/`, 도메인 UI는 `features/`, 공용 UI는 `components/`, 셸은 `widgets/`에 둔다. 작업 전 [frontend/AGENTS.md](frontend/AGENTS.md)와 해당 버전의 로컬 Next.js 문서를 읽는다.
- API 계약의 원본은 백엔드 OpenAPI다. `frontend/src/api-client/generated/`와 `model/`은 수작업 수정하지 않고 재생성한다. 공용 전송·오류·SSE 처리는 기존 클라이언트를 사용한다. 데이터 입력 폼의 스키마를 프런트엔드에 중복 정의하지 않는다.
- 상담의 SSE 계약(`context`, `delta`, `done`, `error`), 취소·오류 표시와 대화 이동 중 스트림 수명을 보호한다. 기능 변경 시 관련 Query 캐시 무효화도 확인한다.
- 상담 실행의 공개 진입점은 `app/modules/advisor/runtime/service.py`의 `ConversationRuntime`이다. 모델 호출은 `ContextAssembler`와 기존 Gateway를 거친다. HTTP 구독 해제로 서버 run을 취소하지 않는다. 앱 전체 1개 실행·대화당 미종결 1개, 질문 ID·revision 기반 재개, 명시적 중지·재시도와 답변 revision을 유지한다. lease·세대 검사와 checkpoint 쓰기 권한을 함께 보호하고 외부 호출 완료가 불명확한 복구는 자동 재호출하지 않는다. 체크포인터 DDL은 Alembic migration 경로에서만 실행한다.
- 웹 조사는 `runtime/graph.py`의 `web_search` 노드와 `app/modules/web_search/`를 사용한다. 요청별 명시적 허용과 별도의 공개 검색어만 외부 전송하며 개인 데이터로 검색어를 확장하지 않는다. 실제 수집한 본문의 선택된 발췌를 `ContextAssembler`의 예산·스냅샷·출처 검증 경로에 합친다. IP 고정·리다이렉트 검증·크기·시간 한도와 운영 Docker의 수집 거부를 유지한다.
- 한국어 UI를 기본으로 하고 기존 라벨·포맷 유틸리티를 재사용한다. 데이터 없음, 공유 제외, 연결 필요, 오래된 데이터, 부분 성공과 실패를 서로 다른 상태로 표시하고 다음 행동을 제공한다.
- 문서 인덱싱 변경 시 버전 활성화, lease·heartbeat·작업 소유권·재시도 상한·중복 완료 방지를 함께 검토한다. 파생 데이터 처리 실패가 기존 검색 가능한 버전을 없애지 않게 한다.

## DB와 운영 데이터 보호

- SQLite와 PostgreSQL 모두 지원 대상이다. 모델 변경에는 Alembic revision을 포함하고 기존 DB의 업그레이드·데이터 보존을 검증한다. `create_all()` 통과는 마이그레이션 검증이 아니다.
- Docker entrypoint는 DB 준비와 migration 잠금을 기다린 뒤 커밋된 Alembic `head`까지 자동 업그레이드하고, 실패하면 서버를 시작하지 않는다. 대기 한도는 `PERSONAL_OS_MIGRATION_TIMEOUT_SECONDS`(기본 60초), 정비 명령의 자동 적용 우회는 `PERSONAL_OS_AUTO_MIGRATE=0`이다. 기존 설치는 이미지 교체 전에 백업한다. 이력이 없는 기존 DB의 명시적 채택과 알 수 없는 revision 검증을 유지하며 자동 stamp·downgrade하지 않는다. 네이티브 앱 시작은 빈 DB만 초기화하며 기존 DB 업그레이드는 `app.modules.database.migration_manager`와 기존 운영 절차를 따른다.
- 스키마 불일치를 `alembic stamp head`, 테이블 재생성, 볼륨 삭제로 덮지 않는다. 실제 DB 변경·복원·이미지 전환은 백업과 호환성 확인을 선행한다. 토큰 암호화 키와 개인 데이터 볼륨도 함께 보호한다.
- **pytest fixture는 테이블을 삭제한다.** `TEST_DATABASE_URL`에는 폐기 가능한 전용 테스트 DB만 사용한다. 개인 운영 DB를 테스트 대상으로 지정하지 않는다.

## 검증

변경한 동작을 입증하는 가장 작은 의미 있는 검증부터 실행한다. 보안·숫자·마이그레이션·동시성 변경에는 관련 회귀 검증을 포함하고, 영향이 넓으면 전체 검증으로 확장한다. 문서만 변경했으면 경로·명령·코드와의 일치 및 diff를 확인한다.

```bash
# 백엔드: 기본값은 격리된 메모리 SQLite
uv sync --frozen
uv run pytest -q

# 프런트엔드: frontend/에서 실행
corepack yarn install --frozen-lockfile
corepack yarn lint
corepack yarn typecheck
corepack yarn test
corepack yarn build

# API 계약 변경 시: 실행 중인 백엔드 또는 OPENAPI_TARGET의 저장된 스키마 사용
corepack yarn generate-api
```

| 변경 영역 | 우선 확인할 기존 회귀 검증 |
| --- | --- |
| 재무·Sheets·이력 | `tests/test_financial_calculator.py`, `test_runway_api.py`, `test_portfolio.py`, `test_holdings_sheets.py`, `test_holdings_history.py`, `test_value_history.py` |
| 상담에 전달되는 데이터 | `tests/test_advisor_product_context.py`, `test_context_routing.py`, `test_context_budget.py`, `test_calendar_context.py` |
| 공유·문서 근거 | `tests/test_privacy_history.py`, `test_advisor_documents.py`, `test_document_evidence.py`, `test_documents.py` |
| 승인·연결·신뢰 경계 | `tests/test_proposal_race.py`, `test_oauth.py`, `test_google_oauth.py`, `test_llm_failures.py`, `test_local_trust.py` |
| DB 변경 | `tests/test_migration_manager.py`, `test_legacy_database.py`, 도메인 migration 테스트 및 `.github/workflows/ci.yml`의 PostgreSQL 검증 |

테스트는 결과뿐 아니라 **모델에 실제로 전달되는 payload**를 검사한다. 예를 들어 최신 잔고 반영, 공유 제외 후 과거 턴 차단, 요청한 일정 범위, 정확한 계산 결과와 불완전성 플래그를 합성 데이터와 가짜 제공자로 확인한다. 모킹된 요청 경로 통과와 실제 LLM의 답변 품질·OAuth·Sheets 연동 성공을 구별한다. 실제 연동 또는 품질 평가가 필요한 작업에서는 측정한 환경과 결과를 별도로 보고한다.

## 작업 방식과 완료 기준

프로젝트 전용 스킬은 `.agents/skills/`에서 관리한다. 아래 작업에서는 해당 `SKILL.md`만 읽어 적용하며 공통 정책은 이 문서를 따른다. 전역 OMX 스킬과 구분되는 이름을 사용한다.

| 작업 | 스킬 |
| --- | --- |
| 개인정보·재무·승인·실행·API 동작의 테스트 기반 구현 | [personal-os-tdd](.agents/skills/personal-os-tdd/SKILL.md) |
| 원인 불명 오류·성능 저하·동시성 문제의 재현과 수정 | [personal-os-diagnosing-bugs](.agents/skills/personal-os-diagnosing-bugs/SKILL.md) |
| PR·브랜치·미커밋 변경 리뷰와 구현 후 자체 검토 | [personal-os-code-review](.agents/skills/personal-os-code-review/SKILL.md) |

- 시작할 때 Git 상태와 적용되는 지침을 확인하고 관련 호출 경로·스키마·테스트를 읽는다. 관련 없는 변경과 개인 로컬 파일을 보존한다.
- 승인된 가역적 로컬 작업은 구현·검증까지 진행한다. 독립적인 탐색·검증은 네이티브 서브에이전트로 병렬화할 수 있으며 파일 편집 책임은 겹치지 않게 한다. OMX는 실제 런타임 지원이 있거나 명시적으로 요청된 경우에만 사용한다.
- 작은 diff와 기존 유틸리티를 우선한다. 정리·리팩터링은 무엇을 단순화하는지 먼저 밝히고 동작 보존을 확인한다. 요청 없는 의존성 추가나 아키텍처 확장을 피한다.
- 코드 변경 후 영향 경로와 반례를 검토하고 유효한 문제를 해결한다. 완료 보고에는 변경한 사용자 동작, 수행한 검증, 확인하지 못한 외부 연동·환경을 구분한다. 실행하지 않았거나 skip된 검증을 통과로 보고하지 않는다.
- 커밋·푸시·병합·배포와 원격 삭제는 명시적으로 요청된 범위만 수행한다. 요청된 커밋은 결정의 의도를 제목에 쓰고 필요한 경우 `Constraint:`, `Rejected:`, `Tested:`, `Not-tested:` trailer로 맥락을 남긴다.
- 사용법·운영 규칙 변경은 기존 [README.md](README.md), [재무 가이드](docs/finance.md), [문서 상담 가이드](docs/documents.md)에 반영한다. 완료 보고를 위한 별도 계획·진행 문서를 계속 늘리지 않는다.
- 이 파일의 공통 원칙과 [frontend/AGENTS.md](frontend/AGENTS.md)의 프런트엔드 지침을 함께 관리한다. 구조·계약·검증 방법을 변경하면 관련 지침을 갱신하고 중복 정책이나 상충하는 설명을 남기지 않는다.
