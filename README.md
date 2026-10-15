# 정산항해사 프로토타입

2026 해운/항만/물류 AX 혁신 아이디어 공모전 출품 프로토타입입니다.
정산 시나리오(항차 목록, 항차 정산, 계약서 비교, 청구 기한)는 가상 데이터이고,
"실제 AIS 대조" 화면은 실제 선박 AIS 신호를 30분마다 자동 수집해 보여줍니다.

## 구조

- `index.html` : 프로토타입 화면 (정적 웹페이지 한 장)
- `data/ais_state.json` : 자동 수집된 AIS 데이터 (GitHub Actions가 갱신)
- `scripts/fetch_ais.py` : AIS 수집 스크립트
- `.github/workflows/update-ais.yml` : 30분마다 수집을 실행하는 자동 작업

수집에 성공했을 때만 `data/ais_state.json`을 덮어씁니다. 수집이 실패하거나 키가 만료되면
파일을 건드리지 않으므로, 화면에는 마지막으로 성공한 데이터와 그 시각이 그대로 남습니다.

## 설치 순서 (처음 한 번)

1. aisstream.io 에 가입해 API 키를 발급받습니다.
2. GitHub에서 새 저장소를 **Public**으로 만들고, 이 폴더의 파일을 모두 올립니다.
   (`.github` 폴더와 `.nojekyll` 파일도 함께 올려야 합니다.)
3. 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `AISSTREAM_API_KEY`
   - Secret: 발급받은 API 키
4. 저장소 **Settings → Actions → General → Workflow permissions** 에서
   **Read and write permissions** 를 선택하고 저장합니다.
5. 저장소 **Settings → Pages** 에서 Source를 **Deploy from a branch**, Branch를 **main / (root)** 로 저장합니다.
6. **Actions** 탭 → "AIS 데이터 갱신" → **Run workflow** 로 첫 수집을 수동 실행합니다.
   로그에 "갱신 완료: 메시지 N건 …"이 나오면 성공입니다.
7. 몇 분 뒤 `https://<계정이름>.github.io/<저장소이름>/` 에 접속해 "실제 AIS 대조" 화면을 확인합니다.

## 확인할 점

- 로그에 "수신한 위치 신호가 없어 기존 데이터를 유지합니다"가 반복되면 해당 해역의 수신 데이터가
  부족한 것입니다. `scripts/fetch_ais.py`의 `LISTEN_SECONDS`를 늘리거나 해역(`PORTS`)을 넓혀 보세요.
- GitHub의 예약 실행은 서버 사정에 따라 몇 분에서 수십 분 늦게 실행될 수 있습니다.
- 접수 마감 후에는 `index.html`과 스크립트를 수정하지 않습니다. 데이터 파일만 자동으로 갱신됩니다.
