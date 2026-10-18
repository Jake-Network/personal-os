# 개인 문서 기반 상담

문서함(`/documents`)에서 PDF·Markdown·TXT를 올리고 주제를 지정합니다. 상담은 기존 DB의 자산·지원·운동 요약과 관련 문서의 발췌문을 함께 사용합니다. 임베딩은 로컬 Ollama 또는 DenseCore에서 생성하고 PostgreSQL의 pgvector로 검색합니다. 답변 생성에는 설정에서 선택한 LLM 연결을 사용하므로 외부 제공자를 선택했다면 검색된 발췌문과 대화 이력이 해당 제공자에게 전달됩니다. ChatGPT/Codex 구독 로그인은 임베딩 제공자로 사용하지 않습니다.

## 실행

프로젝트 루트에서 Docker 환경 파일을 준비한 뒤 실행합니다. 기존 환경 파일이 있으면 유지하고 필요한 설정만 추가합니다.

```sh
cp docker/env.sample docker/.env
# docker/.env의 POSTGRES_PASSWORD 설정
# --env-file은 Compose의 ${...} 치환에도 같은 값을 전달합니다.
docker compose --env-file docker/.env -f docker/docker-compose.yml --profile rag up -d --build
docker compose --env-file docker/.env -f docker/docker-compose.yml exec embeddings ollama pull bge-m3
```

모델은 처음 한 번 내려받으며 약 1.2GB의 모델 저장 공간이 필요합니다. CPU로 실행할 수 있습니다. 모델이 준비되기 전에 올린 문서는 처리 실패가 표시되면 문서함에서 재시도합니다. 로컬 모델 서버 이외의 임베딩 서비스로 자동 전환하지 않습니다.

호스트에서 백엔드를 실행할 때는 Ollama를 별도로 실행하고 다음 환경을 사용합니다.

```sh
export EMBEDDING_URL=http://127.0.0.1:11434
export EMBEDDING_PROVIDER=ollama
export EMBEDDING_MODEL=bge-m3
export EMBEDDING_DIMENSIONS=1024
```

Docker 앱의 기본 임베딩 주소는 내부 서비스 `http://embeddings:11434`입니다. 호스트 설정을 Docker에 그대로 넣지 않도록 합니다. 모델이나 차원을 바꾸면 기존 벡터는 현재 검색에서 제외됩니다. 문서함의 `다시 색인` 버튼 또는 `POST /api/documents/{id}/reindex`로 저장된 파일을 다시 처리합니다. 파일을 재업로드할 필요가 없습니다. 새 버전이 준비될 때까지 이전 파일·발췌문은 보존하며, 과거 상담의 맥락에서는 과거 버전임을 표시합니다.

### DenseCore와 Qwen3 임베딩

Qwen3-Embedding-0.6B GGUF를 로드한 DenseCore 서버가 있다면 다음 설정으로 연결합니다. `EMBEDDING_URL`은 `/v1`을 붙이지 않은 기본 주소이며 앱 컨테이너에서 접근할 수 있어야 합니다. 기존 Ollama 서비스는 이 설정에 사용하지 않습니다.

```sh
export EMBEDDING_PROVIDER=densecore
export EMBEDDING_URL=http://127.0.0.1:18080
export EMBEDDING_MODEL=Qwen3-Embedding-0.6B
export EMBEDDING_DIMENSIONS=1024
# GET /v1/models 응답의 실제 data[0].id와 정확히 일치시킵니다.
export EMBEDDING_DENSECORE_MODEL_ID=Qwen3-Embedding-0.6B-Q8_0
```

DenseCore에는 `/v1/embeddings`로 `pooling_type=last`, `normalize=true`를 전송합니다. Qwen3 검색 질문에만 영어 `Instruct: ...\nQuery:...` 접두사를 붙이고 문서 조각은 원문으로 보냅니다. 이는 [Qwen 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)의 검색 지침을 따릅니다. 응답 index를 원래 입력 순서로 복원하고 개수·차원·유한 값·영벡터 여부를 검사합니다.

DenseCore 임베딩 응답의 `model` 필드는 요청을 그대로 돌려주므로 실제 가중치 확인으로 쓰지 않습니다. 매 요청/배치 전에 `/v1/models`의 로드 모델 ID와 비어 있지 않은 경로 필드를 확인합니다. 이 ID는 파일명 기반이며 파일 내용이나 경로의 실제 존재를 검증하지 않습니다. 한 서버를 전용 임베딩 인스턴스로 운영하고 색인·검색 도중 모델을 교체하지 마세요. GGUF 양자화·가중치 또는 임베딩 방법을 바꿀 때도 `EMBEDDING_MODEL`에 구별되는 이름을 지정하고 기존 문서를 다시 색인해야 벡터 공간이 섞이지 않습니다. 요청 실패 시 다른 제공자로 자동 전환하지 않습니다.

Qwen3-Embedding-0.6B Q8_0의 실제 Docker·API·PostgreSQL 실행 결과와 품질 한계는 [E2E 평가 보고서](evaluations/densecore-qwen3-rag-2026-10-18.md)에 있습니다. 이 검증에는 DenseCore의 계산 그래프 등록, EOS 메타데이터, Qwen3 RoPE 수정이 포함되므로 같은 모델 이름을 쓰는 기존 이미지가 동일하게 동작한다고 가정하면 안 됩니다.

DB 이미지는 기존 `postgres:17-alpine`과 같은 Alpine/musl 기반에 고정된 pgvector 소스를 빌드해 추가합니다. 앱 시작 시에는 빈 DB만 커밋된 Alembic revision으로 만들고, 테이블이 있는 기존 DB는 변경·마이그레이션·stamp하지 않습니다(head보다 뒤처지면 경고만 남깁니다). 기존 DB 업그레이드는 `uv run python -m app.modules.database.migration_manager --apply`로 명시적으로 실행합니다([Finance 문서](finance.md#database-upgrades)). 문서 기능 branch와 `0005_manual_value_history`는 `0006_merge_documents_value_history`에서 합쳐집니다. 이력이 없는 기존 DB에는 아래 명시적 전환 절차를 사용합니다. 이미 Debian/glibc 이미지로 초기화한 볼륨은 Alpine에 직접 연결하지 말고 아래 이미지 전환 절차를 먼저 읽으세요.

```sh
make db-current db-history db-check COMPOSE='docker compose --env-file docker/.env -f docker/docker-compose.yml'
```

문서 기능 최초 revision `6581e3048ce0`까지 제거해 이전 revision으로 롤백하면 업로드 파일·문서 버전·본문·임베딩이 삭제됩니다. 필요한 문서는 롤백 전에 별도로 보관해야 합니다. 공유 확장인 `vector`는 롤백해도 제거하지 않습니다.

## 기존 create_all DB의 명시적 전환

테이블은 있지만 Alembic 이력이 없는 DB는 앱이 그대로 사용하며 baseline DDL을 실행하지 않습니다. 먼저 기존 DB와 OAuth 암호화 키·`app_data`를 백업하고 쓰기를 중지합니다. 앱을 띄우지 않아도 일회성 컨테이너로 검사할 수 있습니다. 새 의존성이 들어간 앱 이미지를 먼저 빌드하세요.

```sh
docker compose --env-file docker/.env -f docker/docker-compose.yml build app
make db-adopt-legacy             # 검사만 수행
make db-adopt-legacy APPLY=1     # 검사한 옛 revision 채택 후 successor 적용
```

검사는 현재 모델이 아니라 frozen `0001`–`0004` revision을 재생한 스키마와 비교합니다. 테이블·열·타입·nullability·기본값·PK·FK·인덱스·제약 중 하나라도 다르면 변경하지 않고 거부합니다. 이미 Alembic 이력이 있는 DB도 이 명령으로 덮어쓰지 않습니다. 검증을 통과한 경우에만 `APPLY=1`이 기존 revision을 명시적으로 기록하고 최신 revision까지 한 트랜잭션으로 진행합니다. 기존 자산·월별 snapshot 행은 유지하고 옛 create_all에서 빠진 append-only trigger는 새 revision이 복구합니다. 임의의 `alembic stamp head`로 우회하지 마세요.

새 revision `25ae62365383`은 작업 lease, 파생 청크 중복 방지, 문서별 snapshot 인덱스와 출처 삭제 표시를 추가합니다. 기존 snapshot의 직접·간접 문서 의존성은 일회성 배치로 backfill합니다. 이전 경쟁 작업이 같은 버전·순서로 만든 중복 파생 청크는 가장 오래된 ID 하나를 보존합니다. 원본 파일과 snapshot에 보관된 발췌문은 유지합니다. 적용·롤백 중에는 인덱싱 작업자를 정지해야 합니다. 롤백은 lease/provenance 메타데이터를 제거하며 정리한 중복 청크 ID는 복원하지 못합니다.

## PostgreSQL 이미지와 collation

`postgres:17-alpine`은 musl, 이전에 사용한 `pgvector/pgvector:pg17`은 다른 OS/libc 기반일 수 있습니다. 같은 PostgreSQL major 버전이어도 기존 볼륨을 다른 libc·locale·ICU 환경에 바로 연결하면 정렬 규칙과 텍스트 인덱스가 맞지 않을 수 있습니다. 이 버전은 원래 Alpine 계열을 유지하지만, **이미 Debian/glibc에서 만든 볼륨을 Alpine으로 되돌리는 것도 직접 수행하면 안 됩니다.**

전환 전에는 실행 중인 기존 환경에서 논리 백업을 만들고 실제 provider·locale·버전을 기록합니다. 교차 OS/libc 전환은 새 볼륨을 대상 이미지로 초기화하고 `pg_dump`/`pg_restore` 또는 SQL dump를 복원해 인덱스를 새 환경에서 만드는 절차를 권장합니다. 원래 볼륨은 복원 검증이 끝날 때까지 유지하고, OAuth 키·`app_data`도 일관되게 보관합니다. 앱은 DB 복원과 이력 검증이 끝난 뒤 시작합니다.

같은 provider의 라이브러리 버전만 바뀌었다면 영향을 받는 인덱스를 재구축한 뒤에만 collation 버전을 갱신합니다. 다음은 관리자가 실제 DB명과 영향을 확인한 후 실행할 SQL 예시이며, 앱이 자동 실행하지 않습니다.

```sql
SELECT datname, datlocprovider, datcollate, datctype, datcollversion,
       pg_database_collation_actual_version(oid)
FROM pg_database WHERE datname = current_database();

-- 같은 provider에서 재구축이 적절함을 확인한 경우, 대상 DB에 연결해 트랜잭션 밖에서:
REINDEX DATABASE personal_os;
ALTER DATABASE personal_os REFRESH COLLATION VERSION;
-- 명시적 collation 의존 인덱스도 재구축한 다음 ALTER COLLATION ... REFRESH VERSION
```

`make db-collation-check`와 앱 시작 전 검사는 DB 기본 및 사용 중인 명시적 collation의 기록/실제 버전이 다르면 거부합니다. 이는 provider 변경의 완전한 호환성 증명이 아니며, 버전 정보가 없는 locale의 교차 libc 사용을 안전하게 만드는 기능도 아닙니다. `REFRESH VERSION`만 실행해서 경고를 숨기면 인덱스가 복구되지 않습니다. 절차는 [PostgreSQL ALTER COLLATION 문서](https://www.postgresql.org/docs/17/sql-altercollation.html)와 [ALTER DATABASE 문서](https://www.postgresql.org/docs/17/sql-alterdatabase.html)를 따릅니다.

## 문서 관리

- 파일당 10MB, 추출 텍스트 50만 자, 최대 500페이지·500조각을 지원합니다.
- 텍스트 PDF와 UTF-8 Markdown/TXT를 지원합니다. 스캔 PDF OCR, 암호화 PDF, 복잡한 재무 표의 구조화 입력은 지원하지 않습니다.
- 주제는 여러 개 지정할 수 있습니다. 문서 종류와 기준일, 연결할 채용 지원·목표도 저장할 수 있습니다.
- 대기 → 처리 중 → 검색 가능으로 상태가 바뀝니다. 실패 원인을 확인하고 재시도할 수 있습니다. 작업자가 종료되면 lease 만료 후 재처리하며, 다른 살아 있는 작업자의 작업은 초기화하지 않습니다.
- 새 파일은 별도 버전으로 처리합니다. 새 버전이 완성되기 전에는 기존 버전이 검색됩니다. 실패하면 기존 버전을 유지합니다.
- 작업은 DB의 원자적 claim과 만료 시간으로 소유자를 정하고 heartbeat로 갱신합니다. 여러 앱 작업자가 실행돼도 살아 있는 lease는 회수하지 않으며, 이전 소유자의 늦은 완료·실패·취소는 새 소유자의 결과를 덮어쓰지 못합니다. 새 업로드와 재시도는 같은 프로세스의 작업자를 깨우고, 다른 프로세스의 작업 및 만료 lease는 최대 약 15초 간격으로 확인합니다. 작업자 DB I/O는 이벤트 루프 밖에서 실행합니다.

## 상담과 근거

채팅에서 문서 검색을 켜고 자동 검색 또는 최대 5개 문서를 지정합니다. 기존 주제 선택으로 검색 영역을 조절할 수 있습니다. 문서를 지정하면 해당 문서의 주제도 조회 대상에 포함하지만 공유 제외 설정은 우선합니다. 후속 질문에도 지정 문서를 유지하며 자동 검색 복귀로 해제할 수 있습니다.

자동 검색은 주제 필터 후 벡터 거리와 단어 일치를 결합합니다. 첫 버전은 정확 벡터 검색을 사용하며 HNSW 인덱스는 추가하지 않았습니다. 작은 개인 문서함에 맞춘 구현이며, 자료가 커지면 실제 검색 지연과 누락률을 측정해 인덱스를 추가합니다. 각 문서의 후보 수는 제한하지만 전체 문서 수는 별도 제한하지 않습니다.

길이 예산 때문에 과거 인용 일부를 포함하지 못해도 대화 전체를 버리지 않습니다. 그 인용 번호만 전송용 이력에서 `과거 문서 근거 생략`으로 바꾸고 한계를 표시합니다. 저장된 원래 답변은 수정하지 않습니다.

답변의 문서 인용을 누르면 답변 당시 스냅샷에 보관한 발췌문·버전·페이지를 확인합니다. 현재 문서의 내용으로 과거 근거를 대체하지 않습니다. Inspector에는 검색에 사용된 발췌문과 검색 실패·자료 부족 표시가 나옵니다. 검색된 문서의 지시문은 신뢰하지 않는 데이터로 취급하도록 응답 지침에 명시합니다. 인용된 주장을 자동으로 참이라고 판정하는 기능은 없습니다.

현재 잔고·수량·순자산에는 구조화 DB의 기준일과 백엔드 계산값을 사용하고, 문서에 다른 값이 있으면 출처와 시점을 구분하도록 합니다. 문서 내용으로 재무 DB를 자동 수정하지 않습니다.

## 공유와 삭제

전역 공유 제외 주제 또는 요청별 제외 주제가 하나라도 붙은 문서는 검색에서 제외합니다. 문서 자체의 공유도 끌 수 있습니다. 공유 해제·삭제·명시적 주제 제외는 해당 근거를 사용한 과거 대화와 후속 답변에도 적용합니다. 검색 주제가 자동으로 바뀌는 것만으로 대화를 제거하지 않습니다. 문서가 교체돼도 공유가 유지되고 이전 버전이 남아 있으면 과거 상담 맥락을 보존하되, 최신 검색과 구분해 표시합니다. 이전 시스템의 snapshot 없는 대화도 기본 상담에서 이어받습니다. 그 맥락을 사용한 답변에는 출처 불명 상태를 전파해, 이후 명시적으로 공유를 제한할 때 우회 재전달되지 않도록 합니다.

문서를 삭제하면 원본·버전·본문·임베딩을 삭제합니다. 기본적으로 과거 답변의 근거 스냅샷은 남습니다. `과거 근거도 삭제`를 선택하면 해당 문서 또는 그 내용을 사용한 후속 대화의 스냅샷도 삭제합니다. 삭제할 snapshot은 문서별 provenance 인덱스로 찾으며 무관한 전체 payload를 읽지 않습니다. 출처가 삭제된 메시지는 단순한 옛 대화와 구분해 재전송을 막습니다. 기존 대화의 사용자 입력과 생성 답변 텍스트는 남으므로, 대화 내용까지 지우려면 상담 대화도 삭제합니다.

## 개발 검증

```sh
uv sync
uv run pytest -q
cd frontend
corepack yarn typecheck
corepack yarn lint
corepack yarn test
```

PostgreSQL 전용 검증은 반드시 폐기 가능한 테스트 DB를 사용합니다. 전체 테스트의 공통 fixture는 테이블을 삭제하므로 애플리케이션 DB를 지정하면 안 됩니다.

```sh
TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:15437/rag_test \
  uv run pytest tests/test_documents.py::test_postgresql_vector_search_and_migration_parity -q
```
