# Capstone_Up_Body_App


# Capstone_Up_Body_App

> 인바디·헬스케어 데이터 기반 AI 운동 미션 생성 및 게임화 챌린지 애플리케이션

FitQuest AI는 사용자의 신체 정보와 활동 데이터를 기반으로 건강 상태를 분석하고, GPT 기반 AI 미션을 생성하여 운동 습관 형성을 돕는 캡스톤 디자인 프로젝트입니다.  
단순히 걸음 수나 체중을 기록하는 앱이 아니라, 사용자 데이터를 공공 평균 데이터와 비교하고, 그 결과를 바탕으로 개인화된 운동 미션을 제공하며, 미션 수행 결과를 캐릭터 성장·EXP·코인·업적·경쟁전으로 연결하는 게임화 헬스케어 서비스입니다.

---

## 프로젝트 개요

기존 헬스케어 앱은 걸음 수, 칼로리, 체중 등 수치를 보여주는 데 집중하는 경우가 많습니다. 하지만 사용자는 자신의 상태가 평균 대비 어떤 수준인지, 어떤 행동을 우선 실천해야 하는지, 지속 가능한 목표가 무엇인지 파악하기 어렵습니다.

FitQuest AI는 이 문제를 해결하기 위해 다음 흐름을 제공합니다.

1. 사용자가 Health Connect 또는 직접 입력을 통해 신체·활동 데이터를 등록합니다.
2. 서버가 사용자 데이터를 공공 평균 데이터와 비교하여 건강 격차를 분석합니다.
3. 분석 결과를 GPT 입력용 요약 데이터로 정제합니다.
4. GPT가 A/B/C 타입의 개인화 미션을 JSON 형태로 생성합니다.
5. 서버가 미션 형식, 타입, 금지 문구, 파라미터, 중복 여부를 검수합니다.
6. 검수된 미션만 DB에 저장되고 사용자에게 제공됩니다.
7. 사용자는 미션을 수행하며 EXP, 코인, 업적, 캐릭터 성장, 상점, 경쟁전 보상을 획득합니다.

---

## 시스템 아키텍처

```text
[Client]
React Native / Expo Dev Client
        │
        │ WebView Bridge
        ▼
React + TypeScript + Vite
        │
        │ REST API
        ▼
[Backend]
FastAPI + Python
        │
        ├─ OpenAI API: AI 미션 생성
        ├─ 공공데이터/KOSIS API: 연령·성별 평균 데이터 조회
        └─ PostgreSQL: 사용자·건강·미션·게임 데이터 저장
```


---

## 주요 기능

### 1. 사용자 인증 및 계정 관리

- 회원가입 / 로그인
- JWT 기반 인증
- 자동 로그인
- 이메일 중복 확인
- 비밀번호 변경
- 로그아웃
- 회원탈퇴
- 프로필 세부 정보 수정
- 프로필 이미지 등록 및 변경
- 14세 미만 가입 제한

---

### 2. 헬스케어 데이터 연동

- React Native 기반 Health Connect 권한 요청
- 키, 몸무게, 걸음 수, 활동 칼로리 수집
- 수동 신체 정보 입력 지원
- Health Connect 동기화 갱신
- 기존 서버값 fallback 처리
- 최근 활동 데이터 기반 히스토리 조회
- 헬스 연동 해제 시 건강 데이터와 AI 미션 데이터만 삭제
- 게임 데이터는 유지되도록 도메인 분리

---

### 3. 공공데이터 기반 건강 비교

- 연령·성별 기준 평균 데이터 조회
- 사용자 키, 몸무게, BMI, 활동량 비교
- 건강 격차 분석
- 목표 체중 및 건강 상태 UI 반영
- 공공데이터 로딩 지연 완화를 위한 캐싱 구조
- KOSIS/공공데이터 API 기반 평균값 활용

---

### 4. GPT 기반 AI 미션 생성

FitQuest AI에서 GPT는 자유롭게 미션을 만드는 생성기가 아니라, 서버 규칙 안에서 동작하는 구조화 생성기로 사용됩니다.

#### AI 미션 생성 원칙

- GPT는 미션 문장, 타입 후보, 파라미터를 생성합니다.
- 서버는 JSON 구조, 허용 타입, 금지 문구, 파라미터, 중복 여부를 검수합니다.
- 검수 통과 미션만 데이터베이스에 저장됩니다.
- 미션 실패 상태는 존재하지 않습니다.
- 미션은 성공 또는 새로고침으로만 교체됩니다.

#### 지원 미션 타입

| 타입 | 설명 | 판정 방식 |
|---|---|---|
| A1_STEP_TARGET | 걸음 수 목표 미션 | 누적 걸음 수 기준 |
| A2_ACTIVE_KCAL_TARGET | 활동 칼로리 목표 미션 | 활동 칼로리 기준 |
| B1_TIMER_STRETCH | 스트레칭 타이머 미션 | 타이머 완료 |
| B2_SLEEP_PREP | 휴식 루틴 타이머 미션 | 타이머 완료 |
| B3_ROUTINE_CHECK | 반복 루틴 체크 미션 | 체크 횟수 달성 |
| C1_HEALTH_CHECKIN | 컨디션 기록 미션 | 기록 입력 및 검수 |

---

### 5. 미션 상태 관리

- A/B/C 슬롯 기반 미션 관리
- 최초 AI 미션 3개 생성
- 미션 성공 시 보상 지급
- 미션 새로고침 기능
- 하루 무료 재생성 횟수 관리
- 무료 횟수 소진 시 미션 쿠폰 사용
- 미션 생성 실패 시 빈 상태 UI 및 다시 생성하기 지원
- 타이머 미션 알림 예약 및 취소
- 화면 이동 후에도 미션 진행 UI 상태 유지

---

### 6. 게임화 시스템

- 게임 프로필 생성
- 게임 닉네임 관리
- EXP / 코인 / 미션 쿠폰 관리
- 수동 레벨업 시스템
- 초과 EXP 이월
- 캐릭터 성장 단계
- 포토카드 UI
- 캐릭터 / 배경 보관함
- 상점 구매 및 장착
- 업적 획득 및 장착
- Week Walk 경쟁전

---

### 7. 업적 시스템

- 첫 미션 완료
- 누적 미션 완료
- 누적 코인 획득
- 레벨 달성
- 첫 결제
- 경쟁전 순위 보상 업적
- 업적 획득 팝업
- 포토카드 배지 장착

---

### 8. Week Walk 경쟁전

Week Walk는 사용자의 걸음 수 데이터를 기반으로 진행되는 시즌형 경쟁전입니다.

- 주간 누적 걸음 수 랭킹
- 경쟁전 참가 기능
- 시즌 종료 타이머
- 순위별 EXP/코인/미션 쿠폰 보상
- 누적 경쟁전 점수
- 티어 시스템
- 순위권 외 처리
- 게임 프로필 생성 유저 기준 참여자 집계

---

## 기술 스택

### Frontend Web

- React
- TypeScript
- Vite
- Zustand
- Tailwind CSS
- Framer Motion

### Mobile Bridge

- React Native
- Expo Dev Client
- WebView
- Health Connect 연동
- Native 권한 요청 및 데이터 브리지

### Backend

- Python
- FastAPI
- SQLAlchemy
- JWT 인증
- OpenAI API 연동
- 공공데이터 / KOSIS API 연동

### Database

- PostgreSQL

---

## 프로젝트 구조

```text
.
├── SRC_REACT_{date}/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── stores/
│   └── package.json
│
├── SRC_REACT_NATIVE_{date}/
│   ├── app/
│   ├── android/
│   ├── assets/
│   └── package.json
│
├── SRC_BACKEND_{date}/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   └── services/
│   └── requirements.txt
│
└── README.md
```

---

## 실행 방법

### 1. Backend 실행

```bash
cd SRC_BACKEND_{date}

python -m venv venv
source venv/bin/activate  # macOS/Linux
# Windows: venv\Scripts\activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. React Web 실행

```bash
cd SRC_REACT_{date}

npm install
npm run dev
```

### 3. React Native 실행

```bash
cd SRC_REACT_NATIVE_{date}

npm install
npx expo start --dev-client
```

---

## 환경 변수 설정

보안상 실제 `.env` 파일은 GitHub에 업로드하지 않습니다.  
아래와 같은 형태로 `.env.example` 파일만 저장소에 포함하는 것을 권장합니다.

### Backend `.env.example`

```env
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/DB_NAME
SECRET_KEY=change-me
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

OPENAI_API_KEY=your-openai-api-key
PUBLIC_DATA_API_KEY=your-public-data-api-key
KOSIS_API_KEY=your-kosis-api-key

TOSS_SECRET_KEY=your-toss-secret-key
```

### Frontend `.env.example`

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_TOSS_CLIENT_KEY=your-toss-client-key
```

---

## 데이터 관리 원칙

FitQuest AI는 건강 데이터와 게임 데이터를 분리하여 관리합니다.

| 상황 | 삭제 대상 | 유지 대상 |
|---|---|---|
| 헬스 연동 해제 | 헬스 데이터, AI 미션 데이터 | 게임 프로필, 캐릭터, 코인, EXP, 업적 |
| 로그아웃 | 로컬 로그인 상태 | 서버 데이터 |
| 회원탈퇴 | 사용자 관련 전체 데이터 | 없음 |

---

## AI 미션 검수 규칙

서버는 GPT가 생성한 미션을 그대로 저장하지 않고 다음 조건을 검사합니다.

- JSON 형식이 올바른가
- 허용된 미션 타입인가
- A/B/C 슬롯 규칙에 맞는가
- 금지 문구가 포함되어 있지 않은가
- 실패, 마감, 제한 시간 표현이 없는가
- 필요한 파라미터가 존재하는가
- 같은 타입이 중복되지 않는가
- 현재 시스템이 판정 가능한 미션인가

금지 표현 예시:

```text
오늘까지
오늘 안에
내일까지
못하면 실패
제한 시간 내
마감
기간 내 완료
24시간 안에
```

---

## 주요 API 예시

### Auth

```text
POST   /auth/signup
POST   /auth/login
GET    /auth/check-username
PATCH  /auth/change-password
POST   /auth/logout
DELETE /auth/delete-account
```

### Healthcare

```text
POST   /healthcare/manual
POST   /healthcare/sync
GET    /healthcare/latest
GET    /healthcare/latest-fast
GET    /healthcare/average
PATCH  /healthcare/target-weight
DELETE /healthcare/unlink
```

### Game

```text
GET    /game/profile
POST   /game/level-up
POST   /game/purchase-character
POST   /game/purchase-background
POST   /game/equip-character
POST   /game/equip-background
```

### Missions

```text
GET    /missions/current
POST   /missions/generate
POST   /missions/complete
POST   /missions/refresh
```

---

## 개발 시 주의사항

- `.env`, `.env.local`, API Key, DB URL, Toss Secret Key는 절대 GitHub에 업로드하지 않습니다.
- `node_modules`, `__pycache__`, `.gradle`, `build`, `debug.keystore`는 저장소에서 제외합니다.
- OpenAI API 응답은 항상 서버 검수 후 저장합니다.
- 건강 데이터는 GPT에 raw DB 그대로 전달하지 않고 요약 데이터만 전달합니다.
- 미션 실패 상태는 만들지 않습니다.
- 게임 상태는 가능한 한 서버 DB 기준으로 관리합니다.

---

## 향후 개선 방향

- AI 미션 추천 이유 설명 기능
- 사용자 미션 수행 성향 기반 난이도 조절
- 디지털 트윈 건강 캐릭터
- 건강 격차 예측 시뮬레이션
- 사용자 변화율 중심 피드백
- 경쟁전 시즌 정산 자동화
- 서버 주도 알림 시스템
- 동시 접속 및 부하 테스트

---

## 프로젝트 성격

본 프로젝트는 소프트웨어학과 캡스톤 디자인 졸업작품으로 제작되었습니다.  
의료 진단 또는 치료 목적의 서비스가 아니며, 사용자의 건강 습관 형성과 운동 동기 부여를 돕는 것을 목적으로 합니다.

---

## 팀

- Team: Debug Lounge
- Project: FitQuest AI
- Category: Healthcare / AI / Gamification / Mobile App
