# DenseCore Qwen3 임베딩 E2E 평가 — 2026-10-18

실제 DenseCore Docker → personal-os HTTP API 업로드 → PostgreSQL pgvector 저장 → 상담 context preview 검색 경로가 통과했다. 초기 DenseCore 결함을 수정한 최종 Q8 모델의 검색 성적은 공식 Transformers 기준과 같았다. personal-os 결합 검색에는 비교·구어체 질문에서 근거를 놓치는 한계가 남아 있다.

## 평가 범위

- 가상 한국어 개인 기록 Markdown **1개**, 제목으로 나뉜 청크 **18개**. 취업·자산·운동 주제를 포함한다.
- 모델 실행 전에 확정한 정답 질문 **24개**, 미기재 사실 질문 **4개**. 영어 질문은 정답 질문 중 **3개**다.
- 복수 근거 질문은 필요한 절을 각각 정답으로 센다. Recall은 질문별 필요한 절 중 검색된 비율의 평균이다. Hit은 필요한 절 하나 이상이 검색됐는지를 뜻한다.
- API 요청은 career/financial/health 범위를 명시했다. 자동 주제 라우팅, 여러 문서 간 검색, 실제 개인 자료, 생성 답변의 정확도는 평가하지 않았다.
- fixture: [고정 질문·정답·문서](../../tests/fixtures/densecore_rag_quality.json), 실행 도구: [evaluate_densecore_rag.py](../../scripts/evaluate_densecore_rag.py).

## 최종 검색 품질

| 지표 | 공식 모델의 로컬 HF float32 실행 | DenseCore Q8 벡터 검색 | personal-os 결합 검색 |
|---|---:|---:|---:|
| Hit@1 | 75.00% | 75.00% | 79.17% |
| 근거 Recall@3 | 93.75% | 93.75% | 87.50% |
| 근거 Recall@6 | 95.83% | 95.83% | 91.67% |
| MRR | 0.8449 | 0.8449 | 0.8403 |

MRR의 기준 순위는 벡터 검색의 경우 전체 18개, API는 반환된 최대 6개다. 결합 검색은 기존 cosine 0.7 + 단어 일치 0.3 정책과 0.35 필터를 유지했다. 이 fixture에 맞춰 점수·임계값·정답 라벨을 조정하지 않았다.

동일한 입력 **46개**의 Q8 DenseCore와 공식 HF float32 벡터 cosine은 최소 **0.998230**, 평균 **0.999115**, 최대 **0.999442**다. 최대 성분 차이는 0.007639. 이는 양자화 모델과 원본의 높은 일치도이며 비트 단위 동일성 검증은 아니다.

## 저장과 API 검증

- `POST /api/documents` → HTTP 201, 문서 ID **3**, 버전 **3**, 최종 상태 `ready`.
- PostgreSQL 실제 열 타입 `vector`, pgvector `0.8.7`, 청크 18개, ordinal 중복 없음, 모두 1024차원.
- 저장 벡터 L2 norm 범위 `0.999999965–1.000000082`. 첫 청크를 다시 생성한 벡터와 DB 값의 최대 차이 **0.0**.
- 검색의 벡터 후보 순위는 PostgreSQL `<=>` cosine 연산으로 확인했고, 최종 근거는 `/api/advisor/context/preview`로 검증했다.
- `/api/documents/chunks/{id}`의 원문 일치, 문서 공유 해제 후 근거 미반환, 공유 복구까지 통과했다.
- 업로드부터 ready까지 24.97초. API 검색 지연 중앙값 0.359초, 최대 0.423초. C++ 빌드가 동시에 실행되던 한 차례 관측이며 성능 비교 벤치마크는 아니다.
- DB Alembic head `25ae62365383`. `db-current`, `db-history`, `db-check`, `db-collation-check` 통과. 생성된 상담 메시지는 0개로, 답변 LLM 호출은 수행하지 않았다.

## 발견·수정한 결함

1. **계산 그래프 누락:** 임베딩 분기가 forward graph 등록 전에 반환해 HTTP 200과 함께 영벡터를 생성했다. production graph 등록을 고치고, 이를 가리던 테스트 helper의 자동 보완을 제거했다. 여러 sequence의 임베딩을 생성용 logits 최적화가 축소하지 않도록 방어했다.
2. **EOS 누락:** GGUF의 `tokenizer.ggml.add_eos_token=true`를 loader와 임베딩 요청이 반영하지 않았다. 모든 46개 입력에서 공식 토큰의 마지막 EOS가 빠진 것을 재현하고 모델 메타데이터 정책을 보존하도록 고쳤다.
3. **RoPE layout 불일치:** 공식 Qwen3 GGUF는 NEOX split-half 가중치 순서다. Qwen3에 NEOX RoPE를 적용하고 NORMAL 방식의 사전 계산 경로를 우회했다. F16 대조에서도 같은 문제가 재현돼 Q8 양자화만의 문제가 아님을 확인했다.
4. **근거 절 누락:** personal-os가 실제로 겹치지 않는 인접 청크도 제거했다. 이제 같은 절·페이지에서 실제 150자 overlap이 확인되는 경우만 중복으로 제거한다.

graph만 수정한 중간 실행의 벡터 Hit@1은 37.50%였고 HF cosine 평균은 0.574795였다. 최종 EOS·RoPE 수정을 포함한 실행은 Hit@1 75.00%와 cosine 평균 0.999115로 회복됐다.

## 남은 품질 한계

- **q06 — 서울·가족·재택 조건의 오퍼 비교:** 두 오퍼 절이 Top6에 없다. 공식 HF도 놓쳤다. 선호 조건을 회사별 오퍼에 연결하는 복합 질의에서 추가 근거 확보가 필요하다.
- **q22 — “쇠질할 때 … 무엇을 우선”:** 정답 근력 운동 절은 벡터 2위(cosine 약 0.3166)지만 API의 고정 0.35 필터와 단어 일치 정책 때문에 사라졌다. 모델별 임계값과 검색 결합 정책은 별도 데이터로 검증해야 한다.
- 미기재 사실 질문 4개 모두에도 관련 절이 반환됐다. 이는 생성 답변이 거짓말했다는 뜻이 아니며, 유사도를 답변 가능성 확률로 쓰면 안 된다. 미기재 사실에 대한 답변 거부 정확도는 별도 평가가 필요하다.
- 단일 합성 문서의 작은 평가이므로 실제 문서함 전체의 정확도나 일반 한국어 성능을 보장하지 않는다.

## 질문별 결과

| ID | 질문 | 필요한 절 | 벡터의 정답 순위 | API의 정답 순위 |
|---|---|---|---|---|
| q01 | 지금 이직할 때 원하는 역할과 일하는 방식은 뭐야? | career_current | career_current: 1 | career_current: 1 |
| q02 | 지난봄에는 어떤 일을 찾았고 지금은 방향이 어떻게 달라졌어? | career_old, career_current | career_old: 1, career_current: 2 | career_old: 1, career_current: 3 |
| q03 | 지원서에서 내가 직접 만든 성과로 내세울 만한 사례는? | project | project: 3 | project: 2 |
| q04 | 지원할 때 어느 버전의 경력 소개서를 보내야 해? | resume | resume: 1 | resume: 1 |
| q05 | 첫해 확정 현금 보수만 보면 두 제안은 어떻게 달라? | offer_a, offer_b | offer_a: 1, offer_b: 5 | offer_a: 6, offer_b: 3 |
| q06 | 가족과 서울에서 지내면서 정기적으로 재택도 할 수 있는 제안은 어느 쪽이야? | offer_a, offer_b | offer_a: 9, offer_b: 12 | offer_a: 미반환, offer_b: 미반환 |
| q07 | 바다가 제시한 지분을 바로 쓸 수 있는 돈으로 봐도 돼? | offer_b | offer_b: 1 | offer_b: 1 |
| q08 | 오로라 수락 기한은 언제야? | offer_a | offer_a: 1 | offer_a: 1 |
| q09 | 최종 채용 대화에서는 어떤 이야기를 연습해야 하지? | interview | interview: 1 | interview: 1 |
| q10 | What is my weekday study routine for job preparation? | learning | learning: 1 | learning: 1 |
| q11 | 지금 가진 현금과 예금, 주식은 각각 얼마나 돼? | assets_current | assets_current: 1 | assets_current: 1 |
| q12 | 봄 이후 통장에 남은 돈과 투자 평가액이 얼마나 변했지? | assets_old, assets_current | assets_old: 1, assets_current: 2 | assets_old: 1, assets_current: 4 |
| q13 | 일을 쉬어도 버티려면 얼마를 따로 남겨 두기로 했어? | emergency | emergency: 2 | emergency: 1 |
| q14 | 통장 잔액 중 마음대로 써도 되는 몫은 얼마야? | emergency | emergency: 3 | emergency: 3 |
| q15 | What is the outstanding loan principal and its annual interest rate? | debt | debt: 1 | debt: 1 |
| q16 | 빚을 먼저 더 갚기 전에 충족해야 할 조건은 뭐야? | debt | debt: 1 | debt: 1 |
| q17 | 장기적으로 매달 넣는 돈은 어느 자산에 어떤 비중으로 가? | investment | investment: 1 | investment: 1 |
| q18 | 살고 있는 집의 계약이 끝나는 날과 매달 관리비를 알려줘. | housing | housing: 1 | housing: 1 |
| q19 | 요즘 유산소 운동을 일주일에 얼마나 하고 어떤 강도로 해? | run_current | run_current: 2 | run_current: 1 |
| q20 | 지난달과 비교해서 달리는 양을 왜 바꿨지? | run_old, run_current | run_old: 1, run_current: 2 | run_old: 1, run_current: 2 |
| q21 | How is my strength training split across the week? | strength | strength: 1 | strength: 1 |
| q22 | 쇠질할 때 무게를 올리는 것보다 무엇을 우선하기로 했어? | strength | strength: 2 | strength: 미반환 |
| q23 | 밤에 공부를 더 하려고 잠을 줄이는 게 내 현재 계획에 맞아? | recovery | recovery: 1 | recovery: 1 |
| q24 | 최근 실제 자는 시간과 목표 수면량은 각각 얼마야? | recovery | recovery: 1 | recovery: 1 |
| u01 | 내 입출금 통장 계좌번호 전체를 알려줘. | 없음 | 미기재 사실 | 미기재 사실 |
| u02 | 최근 혈액 검사에서 공복혈당이 정확히 얼마였어? | 없음 | 미기재 사실 | 미기재 사실 |
| u03 | 솔빛 최종 면접의 화상 회의 접속 URL을 알려줘. | 없음 | 미기재 사실 | 미기재 사실 |
| u04 | 부산으로 이사할 집의 확정 월세와 중개수수료는 얼마야? | 없음 | 미기재 사실 | 미기재 사실 |

## 실행 증거와 재현

- 별도 테스트 환경: DenseCore `127.0.0.1:18081`, personal-os API `127.0.0.1:18082`, PostgreSQL `127.0.0.1:15438/densecore_rag_e2e`.
- 모델: `Qwen/Qwen3-Embedding-0.6B-GGUF`, Q8_0, 저장 namespace `Qwen3-Embedding-0.6B-Q8_0`, last pooling·L2 normalization.
- 실행 이미지: `personal-os-densecore-qwen-e2e:rope`, SHA256 `fdc3a9e5f952d1baceec07ab82238c8069ddf7b273b7d24431e41537f134bfa4`. DenseCore 기준 HEAD는 `faa22b0e33791ef85e1c84056242591989094806`이며 기존 변경과 이번 수정이 함께 포함된 로컬 이미지다.
- GGUF revision `370f27d7550e0def9b39c1f16d3fbaa13aa67728`, SHA256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`.
- 공식 HF revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, Transformers `4.57.6`, torch `2.14.1+cpu`, CPU float32·4 threads.
- fixture SHA256 `43a236af93bee27f82ec0ae85613d85be79dfc3dc1a28a760eb7d1291a1ecaf2`, 업로드 본문 SHA256 `a1d4ab6db6b018fcf590cc56b5d007684a359aab4da6c166efdc1800f8baddbf`.
- 원시 증거 폴더: `/tmp/personal-os-densecore-e2e/`. 최종 `e2e-qualified/summary.json`, `queries.json`, `vectors.json`, `database.json`, `upload.json`; 기준 벡터 `reference/reference_vectors.json`; 실행 소스·이미지·모델 기록 `provenance.json`과 `personal-os-provenance.json`.
- DenseCore는 기존 작업 트리 변경 위에 필요한 수정만 추가했다. 초기 Dockerfile의 decision source stub 누락은 저장소 파일을 바꾸지 않고 기록된 임시 Dockerfile로 빌드했다. 이 결과는 기존 배포 이미지의 검증이 아닌 수정한 로컬 이미지의 검증이다.
- Python 전체 회귀 검증: **231 passed, 5 skipped**. PostgreSQL 실제 저장·검색은 위 E2E에서 별도 확인했다.
- DenseCore C++ 회귀 **17개 통과**. NEOX 대신 이전 NORMAL 설정을 사용한 격리 대조에서 새 RoPE 테스트가 실패했고, 복구 후 17개가 다시 통과했다. `final-cpp-tests.log`, `negative-control-summary.json`, `restored-cpp-tests.log`에 기록했다.
- DenseCore 변경 7개 파일만 분리한 패치는 `/tmp/personal-os-densecore-e2e/densecore-embedding-fix.patch`에 있다. production 수정은 `decoder.cpp`, `model_types.h`, `model_loader.cpp`, `request_builder.cpp`이며, 나머지는 테스트 helper와 회귀 테스트다. 기존 작업 트리 변경은 보존했다.

이미 실행 중인 테스트 API와 비어 있는 폐기 가능한 DB에서 첫 업로드부터 실행하는 명령:

```sh
EMBEDDING_PROVIDER=densecore \
EMBEDDING_URL=http://127.0.0.1:18081 \
EMBEDDING_MODEL=Qwen3-Embedding-0.6B-Q8_0 \
EMBEDDING_DIMENSIONS=1024 \
EMBEDDING_DENSECORE_MODEL_ID=Qwen3-Embedding-0.6B-Q8_0 \
.venv/bin/python scripts/evaluate_densecore_rag.py \
  --database-url postgresql+psycopg://legacy_test:legacy_test@127.0.0.1:15438/densecore_rag_e2e \
  --output /tmp/personal-os-densecore-e2e/repeat \
  --reference-vectors /tmp/personal-os-densecore-e2e/reference/reference_vectors.json
```

현재 저장된 같은 문서로 반복하려면 `--document-id 3`을 추가한다. 이때 summary는 해당 실행에서 HTTP 업로드를 수행하지 않았다고 기록한다. 테스트 계정과 DB는 이 로컬 평가 전용이다.
