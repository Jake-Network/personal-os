---
name: personal-os-tdd
description: Personal OS의 기능·버그 수정을 실패 테스트와 최소 구현으로 진행한다. 개인정보, 재무 계산, 승인, 실행·복구, API 계약 변경에 사용하며 문구·스타일만 바꾸는 작업에는 적용하지 않는다.
license: MIT
metadata:
  upstream: https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/tdd/SKILL.md
---

# Personal OS TDD

루트 `AGENTS.md`를 기준으로 한다. 프런트엔드를 바꿀 때는 `frontend/AGENTS.md`와 관련 로컬 Next.js 문서를 읽는다. 원본의 사용자 사전확인 요구를 기존 계약에서 테스트 경계를 자율 선택하는 방식으로 조정했다. 커밋은 요청된 경우에만 한다. 원본 저작권은 [MIT 라이선스](../LICENSE.mattpocock)에 보존한다.

## 테스트 경계 선택

- 요청에서 기대 동작과 실패 조건을 추출하고 기존 호출 경로·테스트를 확인한다. 테스트할 공개 경계와 잡아낼 반례를 짧게 밝힌 뒤 진행한다. 기존 계약으로 정할 수 없는 제품 의미가 갈릴 때만 질문한다.
- HTTP 계약은 실제 라우터, 상담 실행은 `ConversationRuntime`, 계산은 기존 Decimal 계산 함수처럼 변경한 동작을 관찰할 수 있는 가장 작은 경계를 선택한다. 이미 있는 경계로 검증 가능하면 테스트용 추상화를 추가하지 않는다.
- 모델·시세·검색 등 외부 의존성은 기존 가짜 제공자와 합성 데이터를 사용한다. 내부 서비스 전체를 모킹해 실제 공유 필터·계산·영속성 경로를 건너뛰지 않는다.
- 개인정보 검증은 최종 모델 전송 payload를 검사한다. DB migration, append-only 이력, 감사 기록, lease·generation 검증은 폐기 가능한 DB를 직접 조회해도 된다. 반환값만으로 영속성 보장을 대신하지 않는다.

## 한 동작씩 진행

1. 기대 결과가 독립적으로 정해진 테스트 하나를 작성한다. 계산 기대값은 손으로 확인한 합성 사례나 명시된 계약에서 얻는다.
2. 해당 테스트를 실행해 **수정하려는 동작 때문에 실패**하는지 확인한다. import·환경·네트워크 실패는 동작 재현으로 세지 않는다. 이미 통과하면 잡지 못한 반례인지 확인하고 불필요한 테스트는 추가하지 않는다.
3. 통과시키는 최소 변경을 구현하고 같은 테스트를 재실행한다. 필요한 다음 동작에 대해 반복한다. 테스트를 전부 먼저 쓰거나 추측한 기능까지 구현하지 않는다.
4. 중복이나 복잡성을 줄일 필요가 있으면 통과 상태에서 작게 정리하고 관련 테스트를 재실행한다. 영향 경로와 반례를 자체 검토한 뒤 필요한 범위로 검증을 넓힌다.

## Personal OS 검증 선택

루트 `AGENTS.md`의 영역별 회귀 검증 표를 우선 사용한다. 상담 runtime은 `tests/test_advisor_runtime_execution.py`, `tests/test_advisor_runtime_persistence.py`, 이력 예산은 `tests/test_runtime_history_budget.py`도 확인한다.

- 백엔드는 루트에서 `uv run pytest -q tests/<관련 파일>.py`로 시작한다. fixture가 테이블을 삭제하므로 `TEST_DATABASE_URL`은 기본 격리 SQLite 또는 확인된 폐기용 DB만 사용한다.
- 스키마 변경은 모델과 Alembic revision을 함께 만들고 기존 데이터가 있는 DB의 업그레이드를 검증한다. `create_all()`만 통과한 결과로 완료하지 않는다.
- 프런트엔드는 `frontend/`에서 `corepack yarn test <관련 파일>`을 실행한다. 영향에 따라 lint·typecheck·build를 수행하고 API 변경은 기존 Orval 경로로 재생성한다. 화면·SSE 변경의 브라우저 확인 여부를 별도로 기록한다.
- 중단·재개, 중복 승인, 계정 전환, 공유 해제 후 후속 질문 등 변경과 관련된 실패 경로를 선택한다. 모든 작업에 동일한 전체 체크리스트를 강제하지 않는다.

완료 시 변경 동작, 실제 실행한 실패·통과 검증, 남은 한계를 보고한다. 가짜 제공자 테스트는 실제 LLM 품질·OAuth·Sheets 연동 검증과 구분한다.
