# 로컬 재무 기록과 시세

계좌·잔액·보유 수량·평균단가·부채·거래는 이 컴퓨터의 DB가 원본입니다. Google 연결 없이 입력하고 조회할 수 있습니다. 대시보드와 상담도 같은 로컬 기록을 사용합니다. `/data/holdings`에서 보유 종목을, 나머지 데이터 화면에서 계좌·부채·환율 등을 관리합니다. `/finance`는 백엔드가 계산한 평가액을 보여줍니다. 누락된 가격·환율·기준일은 0으로 대체하지 않습니다.

## Google은 시세 전용

`/finance`에서 Google 연결 후 **시세 전용 파일 새로 만들기**를 선택합니다. 앱이 새 파일에 `Quotes`와 `FX`만 생성합니다. 전송 값은 정규화한 거래소·티커·통화쌍과 서버가 생성한 수식입니다. 계좌명·수량·원가·평가액·로컬 ID·메모는 보내지 않습니다. Google에는 조회 티커 목록이 남습니다.

Google Cloud에서 Sheets API를 활성화하고 웹 애플리케이션 OAuth 클라이언트를 발급합니다. 요청 scope는 `openid`, `email`, `https://www.googleapis.com/auth/drive.file`입니다. `drive.file`은 특정 파일 접근 권한이며 탭 단위 제한이 아닙니다. 기존 자산 파일을 재사용하지 않습니다. [Google 공식 scope 설명](https://developers.google.com/workspace/sheets/api/scopes)

```dotenv
GOOGLE_OAUTH_CLIENT_ID=your-client-id
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
# 운영용 compose에서는 웹 서버를 통해 callback을 전달합니다.
GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:5173/api/finance/google/callback
```

네이티브 개발에서 백엔드로 직접 callback을 받으려면 포트를 8000으로 설정하고 같은 URI를 Google Console에 등록합니다. 브라우저의 호스트는 항상 같아야 합니다. `localhost`와 `127.0.0.1`은 다른 쿠키 호스트입니다. OAuth 시작 시 앱 잠금이 해제되어 있어야 하며, 잠금·세션 만료 후 callback은 거부됩니다. Google과 ChatGPT 연결은 서로 독립입니다.

과거의 `spreadsheets` 또는 `spreadsheets.readonly` 승인은 코드의 scope 변경만으로 철회되지 않습니다. [Google 계정 연결 관리](https://myaccount.google.com/connections)에서 기존 승인을 해제하고 다시 연결하세요. 과거 Google 파일의 개인정보도 자동 삭제하지 않습니다. 이전 완료 후 원격 파일 잔존 여부를 직접 확인하세요.

수동·자동 갱신은 5분 공통 제한을 적용합니다. 같은 종목은 여러 계좌에 있어도 한 번만 조회합니다. 새 관측이 아니면 이전 관측 시각을 갱신하지 않습니다. 오류·계산 대기·미지원 종목은 이전 유효 관측을 보존하며 정상 가격으로 바꾸지 않습니다. 미지원 종목에는 출처와 날짜가 있는 수동 가격을 입력하세요. Google 시세는 최대 20분 지연될 수 있고 모든 시장·종목을 지원하지 않습니다. 과거 GOOGLEFINANCE 배열은 Sheets API에서 조회할 수 없으므로 월말 종가 자료로 쓰지 않습니다. [GOOGLEFINANCE 공식 설명](https://support.google.com/docs/answer/3093281?hl=en)

## 기존 자료 이전

기존 `PortfolioImport`와 월별 스냅샷은 보존됩니다. `/finance`의 **기존 Sheets 저장 자료를 로컬로 편입**에서 저장된 import ID의 행·누락·충돌을 먼저 확인하고 편입합니다. 원본 파일·계정·행 ID 매핑을 보존하므로 같은 import를 다시 실행해도 중복 생성하지 않습니다. 티커만 같다는 이유로 다른 계좌의 행을 합치지 않습니다. 과거 스냅샷과 수정본은 재계산하지 않습니다.

기존 개인 재무 시트 설정·검증·동기화 API는 종료되었습니다. 시세 연결은 로컬 데이터 편집 권한이나 원본을 결정하지 않습니다. 기존 ADC로 다른 계정에 자동 대체하지 않습니다.

## 거래와 월마감

`/finance/records`에서 수입·지출·이체·매매·배당·이자·수수료·세금·상환을 별도 종류로 기록합니다. 발생일과 기록 시각을 구분하고 이체를 수입으로 집계하지 않습니다. 거래 입력은 기록이며 잔액·보유 수량에 자동 반영됐다고 가정하지 않습니다. 권리변동 역시 확인된 수량을 직접 기록하며 가격 변화로 추정하지 않습니다.

일별 관측 평가 저장은 확정 월말 스냅샷과 다릅니다. `/finance/history`의 월마감 입력에서 과거 수량·잔액·가격·환율·포함 범위의 근거를 명시합니다. 현재 수량이나 현재 가격으로 과거 공백을 채우지 않습니다. 불완전한 합계와 누락 월은 화면에 표시됩니다. 월별 차이는 관측 차이이며 수익이나 저축으로 단정하지 않습니다. 수정은 원래 ID와 revision 연결을 남기는 새 기록입니다.

연간 거래 집계는 기록된 현금흐름의 범위를 나타냅니다. 기록 누락을 0으로 확정하거나 근거 없는 성과·원인 분석을 하지 않습니다. 생활비 런웨이는 생활비로 사용할 수 있는 유동성과 기존 지출 충족 조건을 따릅니다.

## Database upgrades

기존 DB는 시작 시 변경하거나 stamp하지 않습니다. 앱과 worker의 쓰기를 중지하고 DB·문서·키·설정을 함께 백업한 뒤 실행합니다.

```bash
uv run python -m app.modules.database.migration_manager
uv run python -m app.modules.database.migration_manager --apply
```

첫 명령은 읽기 전용 계획입니다. `--apply`는 SQLite 파일을 백업하고 명시적으로 업그레이드합니다. PostgreSQL은 별도 `pg_dump` 백업과 격리 복원 확인을 먼저 수행하세요. `stamp head`, 테이블 재생성, 볼륨 삭제로 불일치를 덮지 않습니다. 백업은 [README](../README.md)의 암호화 절차를 따릅니다.
