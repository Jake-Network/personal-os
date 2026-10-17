# 개인 문서 기반 상담

문서함(`/documents`)에서 PDF·Markdown·TXT를 올리고 주제를 지정합니다. 상담은 기존 DB의 자산·지원·운동 요약과 관련 문서의 발췌문을 함께 사용합니다. 임베딩은 로컬 Ollama에서 생성하고 PostgreSQL의 pgvector로 검색합니다. 답변 생성에는 설정에서 선택한 LLM 연결을 사용하므로 외부 제공자를 선택했다면 검색된 발췌문과 대화 이력이 해당 제공자에게 전달됩니다. ChatGPT/Codex 구독 로그인은 임베딩 제공자로 사용하지 않습니다.

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
export EMBEDDING_MODEL=bge-m3
export EMBEDDING_DIMENSIONS=1024
```

Docker 앱의 기본 임베딩 주소는 내부 서비스 `http://embeddings:11434`입니다. 호스트 설정을 Docker에 그대로 넣지 않도록 합니다. 모델이나 차원을 바꾸면 기존 벡터는 검색에서 제외됩니다. 문서의 새 버전을 올려 재색인해야 합니다.

DB 이미지는 PostgreSQL 17용 pgvector 이미지를 사용합니다. 기존 애플리케이션 데이터 볼륨은 유지합니다. 런타임은 커밋된 Alembic revision만 적용하며 스키마를 자동 생성하거나 이력을 stamp하지 않습니다. 이전 Alembic head `0004_portfolio_identity`에서 업그레이드할 수 있습니다. Alembic 이력이 없는 기존 DB는 이 변경에서 자동 변환하지 않습니다.

```sh
make db-current db-history db-check COMPOSE='docker compose --env-file docker/.env -f docker/docker-compose.yml'
```

새 revision을 롤백하면 업로드 파일·문서 버전·본문·임베딩이 삭제됩니다. 필요한 문서는 롤백 전에 별도로 보관해야 합니다. 공유 확장인 `vector`는 롤백해도 제거하지 않습니다.

## 문서 관리

- 파일당 10MB, 추출 텍스트 50만 자, 최대 500페이지·500조각을 지원합니다.
- 텍스트 PDF와 UTF-8 Markdown/TXT를 지원합니다. 스캔 PDF OCR, 암호화 PDF, 복잡한 재무 표의 구조화 입력은 지원하지 않습니다.
- 주제는 여러 개 지정할 수 있습니다. 문서 종류와 기준일, 연결할 채용 지원·목표도 저장할 수 있습니다.
- 대기 → 처리 중 → 검색 가능으로 상태가 바뀝니다. 실패 원인을 확인하고 재시도할 수 있습니다. 처리 중 서버가 종료되면 다음 시작 시 다시 대기 상태로 복구합니다.
- 새 파일은 별도 버전으로 처리합니다. 새 버전이 완성되기 전에는 기존 버전이 검색됩니다. 실패하면 기존 버전을 유지합니다.
- 이 버전의 인덱싱 작업자는 단일 앱 프로세스 운영을 전제로 합니다. 다중 서버의 작업 lease·분산 복구는 후속 범위입니다.

## 상담과 근거

채팅에서 문서 검색을 켜고 자동 검색 또는 최대 5개 문서를 지정합니다. 기존 주제 선택으로 검색 영역을 조절할 수 있습니다. 문서를 지정하면 해당 문서의 주제도 조회 대상에 포함하지만 공유 제외 설정은 우선합니다. 후속 질문에도 지정 문서를 유지하며 자동 검색 복귀로 해제할 수 있습니다.

자동 검색은 주제 필터 후 벡터 거리와 단어 일치를 결합합니다. 첫 버전은 정확 벡터 검색을 사용하며 HNSW 인덱스는 추가하지 않았습니다. 작은 개인 문서함에 맞춘 구현이며, 자료가 커지면 실제 검색 지연과 누락률을 측정해 인덱스를 추가합니다. 각 문서의 후보 수는 제한하지만 전체 문서 수는 별도 제한하지 않습니다.

답변의 문서 인용을 누르면 답변 당시 스냅샷에 보관한 발췌문·버전·페이지를 확인합니다. 현재 문서의 내용으로 과거 근거를 대체하지 않습니다. Inspector에는 검색에 사용된 발췌문과 검색 실패·자료 부족 표시가 나옵니다. 검색된 문서의 지시문은 신뢰하지 않는 데이터로 취급하도록 응답 지침에 명시합니다. 인용된 주장을 자동으로 참이라고 판정하는 기능은 없습니다.

현재 잔고·수량·순자산에는 구조화 DB의 기준일과 백엔드 계산값을 사용하고, 문서에 다른 값이 있으면 출처와 시점을 구분하도록 합니다. 문서 내용으로 재무 DB를 자동 수정하지 않습니다.

## 공유와 삭제

전역 공유 제외 주제 또는 요청별 제외 주제가 하나라도 붙은 문서는 검색에서 제외합니다. 문서 자체의 공유도 끌 수 있습니다. 공유가 해제되거나 삭제·교체된 문서를 근거로 한 과거 대화는 이후 LLM 이력에서 제외합니다. 후속 답변이 사용한 이전 대화의 문서 의존성도 추적합니다.

문서를 삭제하면 원본·버전·본문·임베딩을 삭제합니다. 기본적으로 과거 답변의 근거 스냅샷은 남습니다. `과거 근거도 삭제`를 선택하면 해당 문서 또는 그 내용을 사용한 후속 대화의 스냅샷도 삭제합니다. 기존 대화의 사용자 입력과 생성 답변 텍스트는 남으므로, 대화 내용까지 지우려면 상담 대화도 삭제합니다.

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
