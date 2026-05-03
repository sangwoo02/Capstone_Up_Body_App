import {
  getGrantedPermissions,
  initialize,
  readRecords,
  requestPermission,
} from "react-native-health-connect";

const REQUIRED_PERMISSIONS = [
  { accessType: "read", recordType: "Steps" },
  { accessType: "read", recordType: "Height" },
  { accessType: "read", recordType: "Weight" },
];

const VITAL_RETRY_COUNT = 3;
const VITAL_RETRY_BASE_DELAY_MS = 1500;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function normalizePermissionValue(value: any) {
  return String(value ?? "")
    .trim()
    .toLowerCase();
}

function hasPermission(granted: any[], target: any) {
  return granted.some(
    (permission) =>
      normalizePermissionValue(permission?.accessType) ===
        normalizePermissionValue(target?.accessType) &&
      normalizePermissionValue(permission?.recordType) ===
        normalizePermissionValue(target?.recordType),
  );
}

function getMissingPermissions(granted: any[]) {
  return REQUIRED_PERMISSIONS.filter(
    (permission) => !hasPermission(granted, permission),
  );
}

function hasAllRequiredPermissions(granted: any[]) {
  return getMissingPermissions(granted).length === 0;
}

function debugHealthConnect(label: string, data?: any) {
  const isDev = Boolean((globalThis as any)?.__DEV__);

  if (!isDev) return;

  try {
    console.log(`[HEALTH_CONNECT] ${label}`, data ?? "");
  } catch {
    // 디버그 로그 실패는 동기화 실패로 처리하지 않는다.
  }
}

export async function ensureHealthConnectReady() {
  const initOk = await initialize();

  if (!initOk) {
    throw new Error("Health Connect 초기화 실패(미설치/미지원 가능)");
  }

  let granted: any[] = [];

  try {
    granted = ((await getGrantedPermissions()) ?? []) as any[];
  } catch (error) {
    debugHealthConnect("getGrantedPermissions 실패", error);
    granted = [];
  }

  debugHealthConnect("현재 허용 권한", granted);

  if (!hasAllRequiredPermissions(granted)) {
    const requested = ((await requestPermission(REQUIRED_PERMISSIONS as any)) ??
      []) as any[];

    debugHealthConnect("권한 요청 결과", requested);

    try {
      granted = ((await getGrantedPermissions()) ?? []) as any[];
    } catch {
      // 일부 환경에서 재조회가 실패하면 requestPermission 반환값으로 최종 판단한다.
      granted = requested;
    }
  }

  if (!hasAllRequiredPermissions(granted)) {
    const missingText = getMissingPermissions(granted)
      .map((permission) => permission.recordType)
      .join(", ");

    throw new Error(
      `Health Connect에서 걸음 수, 키, 몸무게 권한을 모두 허용해야 합니다. 부족한 권한: ${missingText || "확인 불가"}`,
    );
  }

  return true;
}

function toISO(date: Date) {
  return date.toISOString();
}

function formatLocalDate(date: Date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function rangeLastDays(days: number) {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - days);

  return {
    operator: "between" as const,
    startTime: toISO(start),
    endTime: toISO(end),
  };
}

function rangeToday() {
  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);

  return {
    operator: "between" as const,
    startTime: toISO(start),
    endTime: toISO(now),
  };
}

function parseTimestamp(value: any) {
  if (!value) return NaN;

  const timestamp = Date.parse(String(value));
  return Number.isFinite(timestamp) ? timestamp : NaN;
}

function recordTimestamp(record: any) {
  const candidates = [
    record?.time,
    record?.endTime,
    record?.startTime,
    record?.metadata?.lastModifiedTime,
  ];

  const times = candidates
    .map(parseTimestamp)
    .filter((timestamp) => Number.isFinite(timestamp));

  return times.length > 0 ? Math.max(...times) : 0;
}

function pickLatestRecord(records: any[]) {
  return [...records]
    .filter(Boolean)
    .sort((a, b) => recordTimestamp(a) - recordTimestamp(b))
    .at(-1);
}

function summarizeVitalRecord(record: any) {
  if (!record) return null;

  return {
    time: record?.time ?? null,
    startTime: record?.startTime ?? null,
    endTime: record?.endTime ?? null,
    lastModifiedTime: record?.metadata?.lastModifiedTime ?? null,
    dataOrigin: record?.metadata?.dataOrigin ?? null,
    timestampScore: recordTimestamp(record),
  };
}

async function readLatestVitalsWithRetry(
  range: ReturnType<typeof rangeLastDays>,
) {
  let latestHeight: any = null;
  let latestWeight: any = null;
  let lastHeightCount = 0;
  let lastWeightCount = 0;

  for (let attempt = 0; attempt < VITAL_RETRY_COUNT; attempt += 1) {
    const [heightRes, weightRes] = await Promise.all([
      readRecords("Height", { timeRangeFilter: range }),
      readRecords("Weight", { timeRangeFilter: range }),
    ]);

    const heightRecords = (heightRes?.records ?? []) as any[];
    const weightRecords = (weightRes?.records ?? []) as any[];

    lastHeightCount = heightRecords.length;
    lastWeightCount = weightRecords.length;

    latestHeight = pickLatestRecord(heightRecords);
    latestWeight = pickLatestRecord(weightRecords);

    debugHealthConnect("키/몸무게 읽기", {
      attempt: attempt + 1,
      heightCount: lastHeightCount,
      weightCount: lastWeightCount,
      latestHeight: summarizeVitalRecord(latestHeight),
      latestWeight: summarizeVitalRecord(latestWeight),
    });

    if (latestHeight && latestWeight) {
      break;
    }

    if (attempt < VITAL_RETRY_COUNT - 1) {
      await sleep(VITAL_RETRY_BASE_DELAY_MS * (attempt + 1));
    }
  }

  return {
    latestHeight,
    latestWeight,
    heightRecordCount: lastHeightCount,
    weightRecordCount: lastWeightCount,
  };
}

function getHeightMeters(record: any) {
  const value = record?.height?.inMeters;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getWeightKg(record: any) {
  const value = record?.weight?.inKilograms;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export async function hcSync(historyDays: number = 7) {
  await ensureHealthConnectReady();

  // 오늘 걸음 수
  const rToday = rangeToday();
  const stepsRes = await readRecords("Steps", { timeRangeFilter: rToday });
  const stepsToday = (stepsRes?.records ?? []).reduce(
    (sum: number, record: any) => sum + Number(record?.count ?? 0),
    0,
  );

  // 최근 N일 걸음 수 날짜별 합산 (첫 연동이면 크게, 이후는 짧게)
  const stepsHistoryRange = rangeLastDays(historyDays);
  const stepsHistoryRes = await readRecords("Steps", {
    timeRangeFilter: stepsHistoryRange,
  });

  const stepsMap = new Map<string, number>();

  for (const record of stepsHistoryRes?.records ?? []) {
    const rawTime =
      (record as any).startTime ??
      (record as any).time ??
      (record as any).endTime;

    if (!rawTime) continue;

    const dateKey = formatLocalDate(new Date(rawTime));
    const count = Number((record as any).count ?? 0);

    stepsMap.set(dateKey, (stepsMap.get(dateKey) ?? 0) + count);
  }

  const dailySteps = [];
  for (let i = historyDays - 1; i >= 0; i -= 1) {
    const date = new Date();
    date.setDate(date.getDate() - i);
    const dateKey = formatLocalDate(date);

    dailySteps.push({
      date: dateKey,
      steps: stepsMap.get(dateKey) ?? 0,
    });
  }

  // 최근 1년 키/몸무게 최신값
  // 설치 직후 또는 삼성헬스 → Health Connect 반영 직후에는 값이 늦게 보일 수 있어 재시도한다.
  const r365 = rangeLastDays(365);
  const { latestHeight, latestWeight, heightRecordCount, weightRecordCount } =
    await readLatestVitalsWithRetry(r365);

  const heightMeters = getHeightMeters(latestHeight);
  const weightKg = getWeightKg(latestWeight);

  return {
    stepsToday,
    dailySteps,
    height: latestHeight
      ? {
          meters: heightMeters,
          time: latestHeight?.time ?? null,
          startTime: latestHeight?.startTime ?? null,
          endTime: latestHeight?.endTime ?? null,
          lastModifiedTime: latestHeight?.metadata?.lastModifiedTime ?? null,
          dataOrigin: latestHeight?.metadata?.dataOrigin ?? null,
          recordCount: heightRecordCount,
        }
      : null,
    weight: latestWeight
      ? {
          kg: weightKg,
          time: latestWeight?.time ?? null,
          startTime: latestWeight?.startTime ?? null,
          endTime: latestWeight?.endTime ?? null,
          lastModifiedTime: latestWeight?.metadata?.lastModifiedTime ?? null,
          dataOrigin: latestWeight?.metadata?.dataOrigin ?? null,
          recordCount: weightRecordCount,
        }
      : null,
  };
}
