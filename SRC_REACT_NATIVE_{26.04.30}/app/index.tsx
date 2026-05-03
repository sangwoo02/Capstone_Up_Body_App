// app/index.tsx
// 개발자 : 박상우, 장서빈, 오유나, 조병진
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as ImagePicker from "expo-image-picker";
import * as Linking from "expo-linking";
import * as Notifications from "expo-notifications";
import React, { useEffect, useRef, useState } from "react";
import {
  BackHandler,
  PermissionsAndroid,
  Platform,
  SafeAreaView,
  Vibration,
} from "react-native";
import { WebView } from "react-native-webview";
import { hcSync } from "../src/healthConnect";

// ✅ 너의 FastAPI 주소로 바꿔야 함 / ⚠️포트 번호 : 8000
const API_BASE_URL = "http://192.168.0.4:8000";

// ✅ WebView에서 열릴 너의 웹앱 주소로 바꿔야 함 / ⚠️포트 번호 : 8080
const WEB_BASE_URL = "http://192.168.0.4:8080";

// ✅ 기존 전역 키는 마이그레이션 정리용으로만 유지
const LEGACY_HEALTH_FIRST_SYNCED_KEY = "health_first_synced";
const MISSION_TIMER_NOTIFICATION_KEY_PREFIX = "mission_timer_notification:";

// ✅ Android 알림 채널은 한 번 생성되면 중요도 수정이 잘 안 됨
// 그래서 기존 default 대신 미션 타이머 전용 v4 채널 사용
const MISSION_TIMER_NOTIFICATION_CHANNEL_ID = "mission-timer-v5";

// ✅ Android 진동 패턴
const MISSION_TIMER_VIBRATION_PATTERN = [0, 500, 250, 500];
const MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024;

const getStorageUserKey = (payload?: Record<string, any>) => {
  const raw =
    payload?.userId ?? payload?.user_id ?? payload?.username ?? payload?.email;

  if (raw === undefined || raw === null || String(raw).trim() === "") {
    return "anonymous";
  }

  return String(raw).trim();
};

const getHealthFirstSyncedKey = (userKey: string) =>
  `health_first_synced:${userKey}`;

const getMissionTimerStorageKey = (userKey: string, notificationKey: string) =>
  `${MISSION_TIMER_NOTIFICATION_KEY_PREFIX}${userKey}:${notificationKey}`;

const getMissionTimerStoragePrefixForUser = (userKey: string) =>
  `${MISSION_TIMER_NOTIFICATION_KEY_PREFIX}${userKey}:`;

Notifications.setNotificationHandler({
  handleNotification: async () =>
    ({
      shouldShowAlert: true,
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }) as any,
});

export default function Index() {
  const webViewRef = useRef<WebView>(null);
  const [canGoBack, setCanGoBack] = useState(false);
  const [webUrl, setWebUrl] = useState(`${WEB_BASE_URL}/`);
  const pendingPaymentUrlRef = useRef<string | null>(null);

  useEffect(() => {
    if (Platform.OS !== "android") return;

    const backHandler = BackHandler.addEventListener(
      "hardwareBackPress",
      () => {
        if (canGoBack) {
          webViewRef.current?.goBack();
          return true;
        }
        return false;
      },
    );

    return () => backHandler.remove();
  }, [canGoBack]);

  const sendToWeb = (payload: any) => {
    webViewRef.current?.postMessage(JSON.stringify(payload));
  };

  const getIntentPackage = (url: string) => {
    return url.match(/;package=([^;]+);/)?.[1];
  };

  const convertIntentUrl = (url: string) => {
    if (!url.startsWith("intent:")) return url;

    const intentBody = url.replace(/^intent:/, "");
    const [intentPart] = intentBody.split("#Intent");
    const scheme = url.match(/;scheme=([^;]+);/)?.[1];

    if (intentPart.includes("://")) {
      return intentPart;
    }

    if (scheme) {
      return `${scheme}:${intentPart.startsWith("//") ? intentPart : `//${intentPart}`}`;
    }

    return url;
  };

  const isPaymentResultDeepLink = (url: string) => {
    if (!url.startsWith("upbodyapp://")) return false;

    const path = url.replace(/^upbodyapp:\/\//, "").replace(/^\/+/, "");

    return (
      path.startsWith("payment/success") || path.startsWith("payment/fail")
    );
  };

  const appUrlToWebUrl = (url: string) => {
    const withoutScheme = url.replace(/^upbodyapp:\/\//, "");

    const pathAndQuery = withoutScheme.startsWith("/")
      ? withoutScheme
      : `/${withoutScheme}`;

    return `${WEB_BASE_URL}${pathAndQuery}`;
  };

  const openWebUrlFromDeepLink = (targetWebUrl: string) => {
    console.log("[PAYMENT_DEEPLINK] targetWebUrl:", targetWebUrl);

    pendingPaymentUrlRef.current = targetWebUrl;
    setWebUrl(targetWebUrl);

    setTimeout(() => {
      webViewRef.current?.injectJavaScript(`
        window.location.replace(${JSON.stringify(targetWebUrl)});
        true;
      `);
    }, 300);
  };

  const handleIncomingAppUrl = (url?: string | null) => {
    if (!url) return;

    console.log("[PAYMENT_DEEPLINK] received:", url);

    if (!url.startsWith("upbodyapp://")) return;

    if (!isPaymentResultDeepLink(url)) {
      console.log("[PAYMENT_DEEPLINK] ignored non-payment appScheme:", url);
      return;
    }

    const targetWebUrl = appUrlToWebUrl(url);
    openWebUrlFromDeepLink(targetWebUrl);
  };

  useEffect(() => {
    Linking.getInitialURL().then((url) => {
      handleIncomingAppUrl(url);
    });

    const subscription = Linking.addEventListener("url", (event) => {
      handleIncomingAppUrl(event.url);
    });

    return () => {
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    const subscription = Notifications.addNotificationReceivedListener(
      (notification) => {
        console.log("[MISSION_NOTIFICATION_RECEIVED]", {
          identifier: notification.request.identifier,
          title: notification.request.content.title,
          body: notification.request.content.body,
          data: notification.request.content.data,
          trigger: notification.request.trigger,
        });

        const data = notification.request.content.data ?? {};
        const type = String(data.type ?? data.originalType ?? "");

        if (
          type === "mission_timer_done" ||
          type === "mission_timer_done_now" ||
          type === "mission_routine_check_ready" ||
          type === "mission_routine_check_ready_now"
        ) {
          Vibration.cancel();

          setTimeout(() => {
            Vibration.vibrate(MISSION_TIMER_VIBRATION_PATTERN);
          }, 50);
        }
      },
    );

    return () => {
      subscription.remove();
    };
  }, []);

  const safeErrorMessage = async (res: Response) => {
    try {
      const data = await res.json();
      return data?.detail || `${res.status} ${res.statusText}`;
    } catch {
      try {
        const text = await res.text();
        return text || `${res.status} ${res.statusText}`;
      } catch {
        return `${res.status} ${res.statusText}`;
      }
    }
  };

  const ensureNotificationChannels = async () => {
    if (Platform.OS !== "android") return;

    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.HIGH,
      sound: "default",
      enableVibrate: true,
      vibrationPattern: MISSION_TIMER_VIBRATION_PATTERN,
    });

    await Notifications.setNotificationChannelAsync(
      MISSION_TIMER_NOTIFICATION_CHANNEL_ID,
      {
        name: "미션 타이머 알림",
        importance: Notifications.AndroidImportance.MAX,
        sound: "default",
        enableVibrate: true,
        vibrationPattern: MISSION_TIMER_VIBRATION_PATTERN,
      },
    );
  };

  const requestNotificationPermission = async (payload?: {
    openSettingsIfDenied?: boolean;
  }) => {
    await ensureNotificationChannels();

    const current = await Notifications.getPermissionsAsync();

    if (current.granted) {
      return {
        granted: true,
        status: current.status,
        canAskAgain: current.canAskAgain,
        openedSettings: false,
      };
    }

    const shouldOpenSettings =
      payload?.openSettingsIfDenied === true || current.canAskAgain === false;

    if (shouldOpenSettings) {
      try {
        await Linking.openSettings();
      } catch (error) {
        console.warn("알림 설정 화면 열기 실패:", error);
      }

      return {
        granted: false,
        status: current.status,
        canAskAgain: current.canAskAgain,
        openedSettings: true,
      };
    }

    const requested = await Notifications.requestPermissionsAsync();

    await ensureNotificationChannels();

    return {
      granted: requested.granted,
      status: requested.status,
      canAskAgain: requested.canAskAgain,
      openedSettings: false,
    };
  };

  const estimateBase64Size = (base64Text: string) => {
    const padding = base64Text.endsWith("==")
      ? 2
      : base64Text.endsWith("=")
        ? 1
        : 0;

    return Math.max(0, Math.floor((base64Text.length * 3) / 4) - padding);
  };

  const requestImagePermission = async (payload?: {
    openSettingsIfDenied?: boolean;
  }) => {
    if (Platform.OS !== "android") {
      const current = await ImagePicker.getMediaLibraryPermissionsAsync();

      if (current.granted) {
        return {
          granted: true,
          status: current.status,
          canAskAgain: current.canAskAgain,
        };
      }

      const requested = await ImagePicker.requestMediaLibraryPermissionsAsync();

      return {
        granted: requested.granted,
        status: requested.status,
        canAskAgain: requested.canAskAgain,
      };
    }

    const androidVersion =
      typeof Platform.Version === "number"
        ? Platform.Version
        : Number.parseInt(String(Platform.Version), 10);

    const openSettingsIfNeeded = async (shouldOpen: boolean) => {
      if (!shouldOpen || !payload?.openSettingsIfDenied) return;

      try {
        await Linking.openSettings();
      } catch {
        // ignore
      }
    };

    if (androidVersion >= 33) {
      const READ_MEDIA_IMAGES =
        PermissionsAndroid.PERMISSIONS.READ_MEDIA_IMAGES;

      const READ_MEDIA_VIDEO = PermissionsAndroid.PERMISSIONS.READ_MEDIA_VIDEO;

      const READ_MEDIA_VISUAL_USER_SELECTED =
        (PermissionsAndroid.PERMISSIONS as any)
          .READ_MEDIA_VISUAL_USER_SELECTED ??
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED";

      const supportsPartialPhotoAccess = androidVersion >= 34;

      const hasImagePermission =
        await PermissionsAndroid.check(READ_MEDIA_IMAGES);

      const hasVideoPermission =
        await PermissionsAndroid.check(READ_MEDIA_VIDEO);

      const hasSelectedPhotoPermission = supportsPartialPhotoAccess
        ? await PermissionsAndroid.check(READ_MEDIA_VISUAL_USER_SELECTED as any)
        : false;

      if (hasImagePermission || hasSelectedPhotoPermission) {
        return {
          granted: true,
          status: hasImagePermission ? "granted" : "limited",
          canAskAgain: true,
          platform: "android",
          permissions: {
            images: hasImagePermission ? "granted" : "denied",
            video: hasVideoPermission ? "granted" : "denied",
            visualSelected: hasSelectedPhotoPermission ? "granted" : "denied",
          },
        };
      }

      const permissionsToRequest: any[] = [READ_MEDIA_IMAGES, READ_MEDIA_VIDEO];

      if (supportsPartialPhotoAccess) {
        permissionsToRequest.push(READ_MEDIA_VISUAL_USER_SELECTED);
      }

      const result = (await PermissionsAndroid.requestMultiple(
        permissionsToRequest as any,
      )) as Record<string, string>;

      const imageStatus = result[String(READ_MEDIA_IMAGES)];
      const videoStatus = result[String(READ_MEDIA_VIDEO)];
      const selectedPhotoStatus = supportsPartialPhotoAccess
        ? result[String(READ_MEDIA_VISUAL_USER_SELECTED)]
        : undefined;

      const imageGranted = imageStatus === PermissionsAndroid.RESULTS.GRANTED;

      const selectedPhotoGranted =
        selectedPhotoStatus === PermissionsAndroid.RESULTS.GRANTED;

      const granted = imageGranted || selectedPhotoGranted;

      const blocked =
        imageStatus === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN ||
        videoStatus === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN ||
        selectedPhotoStatus === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN;

      await openSettingsIfNeeded(!granted && blocked);

      return {
        // 전체 사진 권한이거나 Android 14+ 선택한 사진 권한이면 통과
        granted,
        status: imageGranted
          ? "granted"
          : selectedPhotoGranted
            ? "limited"
            : blocked
              ? "blocked"
              : "denied",
        canAskAgain: !blocked,
        platform: "android",
        permissions: {
          images: imageStatus,
          video: videoStatus,
          visualSelected: selectedPhotoStatus,
        },
      };
    }

    const READ_EXTERNAL_STORAGE =
      PermissionsAndroid.PERMISSIONS.READ_EXTERNAL_STORAGE;

    const hasLegacyPermission = await PermissionsAndroid.check(
      READ_EXTERNAL_STORAGE,
    );

    if (hasLegacyPermission) {
      return {
        granted: true,
        status: "granted",
        canAskAgain: true,
        platform: "android",
        permissions: {
          storage: "granted",
        },
      };
    }

    const result = await PermissionsAndroid.request(READ_EXTERNAL_STORAGE);

    const granted = result === PermissionsAndroid.RESULTS.GRANTED;
    const blocked = result === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN;

    await openSettingsIfNeeded(!granted && blocked);

    return {
      granted,
      status: granted ? "granted" : blocked ? "blocked" : "denied",
      canAskAgain: !blocked,
      platform: "android",
      permissions: {
        storage: result,
      },
    };
  };

  const pickProfileImage = async (payload?: {
    source?: "gallery";
    maxBytes?: number;
    allowsEditing?: boolean;
    quality?: number;
    openSettingsIfDenied?: boolean;
  }) => {
    const permission = await requestImagePermission({
      openSettingsIfDenied: payload?.openSettingsIfDenied,
    });

    if (!permission.granted) {
      return {
        cancelled: true,
        source: "gallery",
        permission,
      };
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes:
        (ImagePicker as any).MediaTypeOptions?.Images ??
        (ImagePicker as any).MediaType?.Images ??
        "images",
      allowsEditing: payload?.allowsEditing ?? true,
      aspect: [1, 1],
      quality:
        typeof payload?.quality === "number" && Number.isFinite(payload.quality)
          ? Math.min(1, Math.max(0, payload.quality))
          : 0.85,
      base64: true,

      // Android에서는 Photo Picker보다 기존 갤러리 접근 방식에 가깝게 실행
      legacy: Platform.OS === "android",
      defaultTab: Platform.OS === "android" ? "albums" : undefined,
    } as any);

    if (result.canceled || !result.assets?.length) {
      return {
        cancelled: true,
        source: "gallery",
        permission,
      };
    }

    const asset = result.assets[0];
    const mimeType = asset.mimeType || "image/jpeg";
    const base64Text = asset.base64 || "";

    if (!base64Text) {
      throw new Error("선택한 이미지를 base64 데이터로 읽지 못했습니다.");
    }

    const sizeBytes =
      typeof asset.fileSize === "number" && asset.fileSize > 0
        ? asset.fileSize
        : estimateBase64Size(base64Text);

    const maxBytes = payload?.maxBytes || MAX_PROFILE_IMAGE_BYTES;

    if (sizeBytes > maxBytes) {
      throw new Error("프로필 이미지는 5MB 이하만 등록할 수 있습니다.");
    }

    return {
      cancelled: false,
      source: "gallery",
      permission,
      uri: asset.uri,
      width: asset.width,
      height: asset.height,
      mimeType,
      fileSize: sizeBytes,
      dataUrl: `data:${mimeType};base64,${base64Text}`,
    };
  };

  const buildMissionNotificationContent = (payload: {
    title: string;
    body: string;
    data?: Record<string, any>;
  }) => {
    return {
      title: payload.title,
      body: payload.body,
      sound: "default",
      priority: Notifications.AndroidNotificationPriority.MAX,
      vibrate: MISSION_TIMER_VIBRATION_PATTERN,
      data: payload.data ?? {},
    } as any;
  };

  const getMissionTimerDelaySeconds = (payload: {
    seconds?: number;
    targetTimeMs?: number;
  }) => {
    const delayFromTargetTime =
      typeof payload.targetTimeMs === "number" &&
      Number.isFinite(payload.targetTimeMs)
        ? Math.ceil((payload.targetTimeMs - Date.now()) / 1000)
        : NaN;

    if (Number.isFinite(delayFromTargetTime) && delayFromTargetTime > 0) {
      return Math.max(1, delayFromTargetTime);
    }

    const delayFromSeconds = Math.ceil(Number(payload.seconds));

    if (Number.isFinite(delayFromSeconds) && delayFromSeconds > 0) {
      return Math.max(1, delayFromSeconds);
    }

    return 1;
  };

  const buildMissionTimerTrigger = (payload: {
    seconds?: number;
    targetTimeMs?: number;
  }) => {
    const now = Date.now();

    if (
      typeof payload.targetTimeMs === "number" &&
      Number.isFinite(payload.targetTimeMs) &&
      payload.targetTimeMs > now + 500
    ) {
      return {
        type: Notifications.SchedulableTriggerInputTypes.DATE,
        date: new Date(payload.targetTimeMs),
        channelId: MISSION_TIMER_NOTIFICATION_CHANNEL_ID,
      } as any;
    }

    return {
      type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
      seconds: getMissionTimerDelaySeconds(payload),
      repeats: false,
      channelId: MISSION_TIMER_NOTIFICATION_CHANNEL_ID,
    } as any;
  };

  const scheduleMissionTimerNotification = async (payload: {
    userKey: string;
    notificationKey: string;
    title: string;
    body: string;
    seconds?: number;
    targetTimeMs?: number;
    data?: Record<string, any>;
  }) => {
    if (!payload.notificationKey || !String(payload.notificationKey).trim()) {
      throw new Error("notificationKey가 비어 있습니다.");
    }

    const hasValidTargetTime =
      typeof payload.targetTimeMs === "number" &&
      Number.isFinite(payload.targetTimeMs) &&
      payload.targetTimeMs > Date.now() + 500;

    const hasValidSeconds =
      typeof payload.seconds === "number" &&
      Number.isFinite(payload.seconds) &&
      payload.seconds > 0;

    if (!hasValidTargetTime && !hasValidSeconds) {
      throw new Error("seconds 또는 targetTimeMs 값이 올바르지 않습니다.");
    }

    const permission = await requestNotificationPermission();

    if (!permission.granted) {
      return {
        scheduled: false,
        reason: "permission_denied",
      };
    }

    await ensureNotificationChannels();

    const storageKey = getMissionTimerStorageKey(
      payload.userKey,
      payload.notificationKey,
    );

    const prevIdentifier = await AsyncStorage.getItem(storageKey);

    if (prevIdentifier) {
      try {
        await Notifications.cancelScheduledNotificationAsync(prevIdentifier);
      } catch {
        // ignore
      }
    }

    const trigger = buildMissionTimerTrigger({
      seconds: payload.seconds,
      targetTimeMs: payload.targetTimeMs,
    });

    const identifier = await Notifications.scheduleNotificationAsync({
      content: buildMissionNotificationContent({
        title: payload.title,
        body: payload.body,
        data: {
          ...(payload.data ?? {}),
          notificationKey: payload.notificationKey,
          userKey: payload.userKey,
        },
      }),
      trigger,
    });

    const scheduledList =
      await Notifications.getAllScheduledNotificationsAsync();

    console.log("[MISSION_NOTIFICATION_SCHEDULED]", {
      identifier,
      notificationKey: payload.notificationKey,
      seconds: payload.seconds,
      targetTimeMs: payload.targetTimeMs,
      scheduledCount: scheduledList.length,
      scheduledList: scheduledList.map((item) => ({
        identifier: item.identifier,
        title: item.content.title,
        body: item.content.body,
        trigger: item.trigger,
      })),
    });

    await AsyncStorage.setItem(storageKey, identifier);

    return {
      scheduled: true,
      identifier,
    };
  };

  const showMissionTimerNotificationNow = async (payload: {
    userKey: string;
    notificationKey?: string;
    title: string;
    body: string;
    data?: Record<string, any>;
  }) => {
    const permission = await requestNotificationPermission();

    if (!permission.granted) {
      return {
        shown: false,
        reason: "permission_denied",
      };
    }

    await ensureNotificationChannels();

    if (payload.notificationKey && String(payload.notificationKey).trim()) {
      const storageKey = getMissionTimerStorageKey(
        payload.userKey,
        payload.notificationKey,
      );

      const prevIdentifier = await AsyncStorage.getItem(storageKey);

      if (prevIdentifier) {
        try {
          await Notifications.cancelScheduledNotificationAsync(prevIdentifier);
        } catch {
          // ignore
        }

        await AsyncStorage.removeItem(storageKey);
      }
    }

    Vibration.cancel();
    Vibration.vibrate(MISSION_TIMER_VIBRATION_PATTERN);

    const identifier = await Notifications.scheduleNotificationAsync({
      content: buildMissionNotificationContent({
        title: payload.title,
        body: payload.body,
        data: {
          ...(payload.data ?? {}),
          notificationKey: payload.notificationKey,
          userKey: payload.userKey,
          immediate: true,
        },
      }),
      trigger: {
        type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
        seconds: 1,
        repeats: false,
        channelId: MISSION_TIMER_NOTIFICATION_CHANNEL_ID,
      } as any,
    });

    console.log("[MISSION_NOTIFICATION_NOW]", {
      identifier,
      notificationKey: payload.notificationKey,
    });

    return {
      shown: true,
      identifier,
    };
  };

  const cancelMissionTimerNotification = async (payload: {
    userKey: string;
    notificationKey: string;
  }) => {
    if (!payload.notificationKey || !String(payload.notificationKey).trim()) {
      throw new Error("notificationKey가 비어 있습니다.");
    }

    const storageKey = getMissionTimerStorageKey(
      payload.userKey,
      payload.notificationKey,
    );

    const identifier = await AsyncStorage.getItem(storageKey);

    console.log("[MISSION_NOTIFICATION_CANCEL_REQUEST]", {
      notificationKey: payload.notificationKey,
      userKey: payload.userKey,
      identifier,
    });

    if (identifier) {
      try {
        await Notifications.cancelScheduledNotificationAsync(identifier);
      } catch {
        // ignore
      }
    }

    await AsyncStorage.removeItem(storageKey);

    const scheduledListAfterCancel =
      await Notifications.getAllScheduledNotificationsAsync();

    console.log("[MISSION_NOTIFICATION_CANCELLED]", {
      notificationKey: payload.notificationKey,
      identifier,
      scheduledCount: scheduledListAfterCancel.length,
      scheduledList: scheduledListAfterCancel.map((item) => ({
        identifier: item.identifier,
        title: item.content.title,
        body: item.content.body,
        trigger: item.trigger,
      })),
    });

    return {
      cancelled: true,
      identifier,
    };
  };

  const cancelAllMissionTimerNotificationsForUser = async (userKey: string) => {
    const prefix = getMissionTimerStoragePrefixForUser(userKey);
    const keys = await AsyncStorage.getAllKeys();
    const targetKeys = keys.filter((key) => key.startsWith(prefix));

    let cancelledCount = 0;

    for (const key of targetKeys) {
      const identifier = await AsyncStorage.getItem(key);

      if (identifier) {
        try {
          await Notifications.cancelScheduledNotificationAsync(identifier);
          cancelledCount += 1;
        } catch {
          // ignore
        }
      }
    }

    if (targetKeys.length > 0) {
      await AsyncStorage.multiRemove(targetKeys);
    }

    return {
      cancelled: true,
      cancelledCount,
      removedStorageKeys: targetKeys.length,
    };
  };

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <WebView
        ref={webViewRef}
        source={{ uri: webUrl }}
        javaScriptEnabled
        domStorageEnabled
        sharedCookiesEnabled
        thirdPartyCookiesEnabled
        cacheEnabled={false}
        cacheMode="LOAD_NO_CACHE"
        originWhitelist={[
          "http://*",
          "https://*",
          "intent://*",
          "market://*",
          "upbodyapp://*",
        ]}
        onShouldStartLoadWithRequest={(request) => {
          const url = request.url;

          if (
            url.startsWith("http://") ||
            url.startsWith("https://") ||
            url === "about:blank"
          ) {
            return true;
          }

          if (url.startsWith("upbodyapp://")) {
            handleIncomingAppUrl(url);
            return false;
          }

          if (url.startsWith("intent:")) {
            const convertedUrl = convertIntentUrl(url);
            const packageName = getIntentPackage(url);

            Linking.openURL(convertedUrl).catch((error) => {
              console.warn(
                "Intent URL 변환 후 열기 실패:",
                convertedUrl,
                error,
              );

              if (packageName) {
                Linking.openURL(`market://details?id=${packageName}`).catch(
                  (marketError) => {
                    console.warn("마켓 이동 실패:", packageName, marketError);
                  },
                );
              }
            });

            return false;
          }

          Linking.openURL(url).catch((error) => {
            console.warn("외부 결제 앱 열기 실패:", url, error);
          });

          return false;
        }}
        onNavigationStateChange={(navState) =>
          setCanGoBack(!!navState.canGoBack)
        }
        onLoadEnd={(syntheticEvent) => {
          const pendingUrl = pendingPaymentUrlRef.current;

          if (!pendingUrl) return;

          const currentUrl = syntheticEvent.nativeEvent.url;

          webViewRef.current?.injectJavaScript(`
            if (window.location.href !== ${JSON.stringify(pendingUrl)}) {
              window.location.replace(${JSON.stringify(pendingUrl)});
            }
            true;
          `);

          if (currentUrl === pendingUrl) {
            pendingPaymentUrlRef.current = null;
          }
        }}
        onMessage={async (event) => {
          try {
            const raw = event.nativeEvent.data;
            const msg = JSON.parse(raw || "{}");

            if (msg.type === "HC_SYNC_REQUEST") {
              const result = await hcSync();
              sendToWeb({
                type: "HC_SYNC_RESULT",
                requestId: msg.requestId,
                ok: true,
                data: result,
              });
              return;
            }

            if (msg.type === "AUTH_SIGNUP_REQUEST") {
              const { requestId, payload } = msg;

              const res = await fetch(`${API_BASE_URL}/auth/signup`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "AUTH_SIGNUP_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "AUTH_SIGNUP_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (
              msg.type === "AUTH_CHECK_USERNAME_REQUEST" ||
              msg.type === "AUTH_CHECK_EMAIL_REQUEST"
            ) {
              const { requestId, payload } = msg;
              const responseType =
                msg.type === "AUTH_CHECK_EMAIL_REQUEST"
                  ? "AUTH_CHECK_EMAIL_RESULT"
                  : "AUTH_CHECK_USERNAME_RESULT";

              const username = String(payload?.username ?? "").trim();

              if (!username) {
                sendToWeb({
                  type: responseType,
                  requestId,
                  ok: false,
                  error: "username이 비어 있습니다.",
                });
                return;
              }

              const encodedUsername = encodeURIComponent(username);
              const res = await fetch(
                `${API_BASE_URL}/auth/check-username?username=${encodedUsername}`,
                {
                  method: "GET",
                },
              );

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: responseType,
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: responseType,
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "AUTH_LOGIN_REQUEST") {
              const { requestId, payload } = msg;

              const form = new URLSearchParams();
              form.append("username", payload.username);
              form.append("password", payload.password);

              const res = await fetch(`${API_BASE_URL}/auth/login`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/x-www-form-urlencoded",
                },
                body: form.toString(),
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "AUTH_LOGIN_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "AUTH_LOGIN_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "AUTH_CHANGE_PASSWORD_REQUEST") {
              const { requestId, payload } = msg;
              const { token, currentPassword, newPassword } = payload;

              const res = await fetch(`${API_BASE_URL}/auth/change-password`, {
                method: "PATCH",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                  current_password: currentPassword,
                  new_password: newPassword,
                }),
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "AUTH_CHANGE_PASSWORD_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "AUTH_CHANGE_PASSWORD_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "AUTH_RESET_PASSWORD_REQUEST") {
              const { requestId, payload } = msg;

              const username = String(payload?.username ?? "").trim();
              const nextPassword = String(
                payload?.new_password ?? payload?.newPassword ?? "",
              ).trim();

              if (!username || !nextPassword) {
                sendToWeb({
                  type: "AUTH_RESET_PASSWORD_RESULT",
                  requestId,
                  ok: false,
                  error: "username 또는 새 비밀번호가 비어 있습니다.",
                });
                return;
              }

              const res = await fetch(`${API_BASE_URL}/auth/reset-password`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                },
                body: JSON.stringify({
                  username,
                  new_password: nextPassword,
                }),
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "AUTH_RESET_PASSWORD_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "AUTH_RESET_PASSWORD_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "AUTH_LOGOUT_REQUEST") {
              const { requestId, payload } = msg;
              const { token } = payload;

              const res = await fetch(`${API_BASE_URL}/auth/logout`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${token}`,
                },
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "AUTH_LOGOUT_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();

              sendToWeb({
                type: "AUTH_LOGOUT_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "AUTH_DELETE_ACCOUNT_REQUEST") {
              const { requestId, payload } = msg;
              const { token } = payload;
              const userKey = getStorageUserKey(payload);

              const res = await fetch(`${API_BASE_URL}/auth/delete-account`, {
                method: "DELETE",
                headers: {
                  Authorization: `Bearer ${token}`,
                },
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "AUTH_DELETE_ACCOUNT_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();

              try {
                await cancelAllMissionTimerNotificationsForUser(userKey);
              } catch {
                // ignore
              }

              sendToWeb({
                type: "AUTH_DELETE_ACCOUNT_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "AUTH_NOTIFICATION_PERMISSION_REQUEST") {
              const { requestId, payload } = msg;

              try {
                const data = await requestNotificationPermission(payload);

                sendToWeb({
                  type: "AUTH_NOTIFICATION_PERMISSION_RESULT",
                  requestId,
                  ok: true,
                  data,
                });
              } catch (error: any) {
                sendToWeb({
                  type: "AUTH_NOTIFICATION_PERMISSION_RESULT",
                  requestId,
                  ok: false,
                  error: error?.message || "알림 권한 요청에 실패했습니다.",
                });
              }
              return;
            }

            if (msg.type === "AUTH_IMAGE_PERMISSION_REQUEST") {
              const { requestId, payload } = msg;

              try {
                const data = await requestImagePermission(payload);

                sendToWeb({
                  type: "AUTH_IMAGE_PERMISSION_RESULT",
                  requestId,
                  ok: true,
                  data,
                });
              } catch (error: any) {
                sendToWeb({
                  type: "AUTH_IMAGE_PERMISSION_RESULT",
                  requestId,
                  ok: false,
                  error:
                    error?.message || "사진 / 이미지 권한 요청에 실패했습니다.",
                });
              }
              return;
            }

            if (msg.type === "PROFILE_IMAGE_PICK_REQUEST") {
              const { requestId, payload } = msg;

              try {
                const data = await pickProfileImage(payload);

                sendToWeb({
                  type: "PROFILE_IMAGE_PICK_RESULT",
                  requestId,
                  ok: true,
                  data,
                });
              } catch (error: any) {
                sendToWeb({
                  type: "PROFILE_IMAGE_PICK_RESULT",
                  requestId,
                  ok: false,
                  error: error?.message || "프로필 이미지 선택에 실패했습니다.",
                });
              }
              return;
            }

            if (msg.type === "MISSION_TIMER_NOTIFICATION_SCHEDULE_REQUEST") {
              const { requestId, payload } = msg;
              const userKey = getStorageUserKey(payload);

              try {
                const data = await scheduleMissionTimerNotification({
                  userKey,
                  notificationKey: payload.notificationKey,
                  title: payload.title,
                  body: payload.body,
                  seconds:
                    payload.seconds === undefined
                      ? undefined
                      : Number(payload.seconds),
                  targetTimeMs:
                    payload.targetTimeMs === undefined
                      ? undefined
                      : Number(payload.targetTimeMs),
                  data: payload.data,
                });

                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_SCHEDULE_RESULT",
                  requestId,
                  ok: true,
                  data,
                });
              } catch (error: any) {
                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_SCHEDULE_RESULT",
                  requestId,
                  ok: false,
                  error:
                    error?.message || "타이머 완료 알림 예약에 실패했습니다.",
                });
              }
              return;
            }

            if (msg.type === "MISSION_TIMER_NOTIFICATION_NOW_REQUEST") {
              const { requestId, payload } = msg;
              const userKey = getStorageUserKey(payload);

              try {
                const data = await showMissionTimerNotificationNow({
                  userKey,
                  notificationKey: payload?.notificationKey,
                  title: payload?.title || "미션 타이머 완료",
                  body: payload?.body || "미션 타이머가 완료되었습니다.",
                  data: payload?.data,
                });

                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_NOW_RESULT",
                  requestId,
                  ok: true,
                  data,
                });
              } catch (error: any) {
                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_NOW_RESULT",
                  requestId,
                  ok: false,
                  error:
                    error?.message || "타이머 완료 알림 표시에 실패했습니다.",
                });
              }
              return;
            }

            if (msg.type === "MISSION_TIMER_NOTIFICATION_CANCEL_REQUEST") {
              const { requestId, payload } = msg;
              const userKey = getStorageUserKey(payload);

              try {
                const data = await cancelMissionTimerNotification({
                  userKey,
                  notificationKey: payload.notificationKey,
                });

                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_CANCEL_RESULT",
                  requestId,
                  ok: true,
                  data,
                });
              } catch (error: any) {
                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_CANCEL_RESULT",
                  requestId,
                  ok: false,
                  error:
                    error?.message || "타이머 완료 알림 취소에 실패했습니다.",
                });
              }
              return;
            }

            if (msg.type === "MISSION_TIMER_NOTIFICATION_CANCEL_ALL_REQUEST") {
              const { requestId, payload } = msg;
              const userKey = getStorageUserKey(payload);

              try {
                const data =
                  await cancelAllMissionTimerNotificationsForUser(userKey);

                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_CANCEL_ALL_RESULT",
                  requestId,
                  ok: true,
                  data,
                });
              } catch (error: any) {
                sendToWeb({
                  type: "MISSION_TIMER_NOTIFICATION_CANCEL_ALL_RESULT",
                  requestId,
                  ok: false,
                  error:
                    error?.message || "전체 미션 알림 취소에 실패했습니다.",
                });
              }
              return;
            }

            if (msg.type === "HC_SYNC_AND_SAVE_REQUEST") {
              const { requestId, payload } = msg;
              const {
                token,
                gender,
                goal,
                force_history_days,
                fallback_height_cm,
                fallback_weight_kg,
              } = payload;

              const toPositiveNumberOrNull = (value: any) => {
                const n = Number(value);
                return Number.isFinite(n) && n > 0 ? n : null;
              };

              const userKey = getStorageUserKey(payload);
              const scopedFirstSyncKey = getHealthFirstSyncedKey(userKey);

              const firstSynced =
                (await AsyncStorage.getItem(scopedFirstSyncKey)) ??
                (await AsyncStorage.getItem(LEGACY_HEALTH_FIRST_SYNCED_KEY));

              const historyDays =
                typeof force_history_days === "number"
                  ? force_history_days
                  : firstSynced
                    ? 14
                    : 30;

              const hc = await hcSync(historyDays);

              const heightMeters = hc?.height?.meters;
              const rawWeightKg = hc?.weight?.kg;

              const healthConnectHeightCm =
                typeof heightMeters === "number" &&
                Number.isFinite(heightMeters)
                  ? heightMeters * 100
                  : null;

              const healthConnectWeightKg =
                typeof rawWeightKg === "number" && Number.isFinite(rawWeightKg)
                  ? rawWeightKg
                  : null;

              // 이미 연동된 사용자의 재동기화/자동동기화에서는 Health Connect가 한쪽 값을
              // 잠깐 못 내려줘도 서버에 저장된 기존 값을 fallback으로 사용한다.
              // 첫 연동처럼 fallback이 없는 경우에는 기존처럼 실패 처리된다.
              const heightCm =
                healthConnectHeightCm ??
                toPositiveNumberOrNull(fallback_height_cm);
              const weightKg =
                healthConnectWeightKg ??
                toPositiveNumberOrNull(fallback_weight_kg);

              if (
                typeof heightCm !== "number" ||
                typeof weightKg !== "number"
              ) {
                sendToWeb({
                  type: "HC_SYNC_AND_SAVE_RESULT",
                  requestId,
                  ok: false,
                  error:
                    "키/몸무게 데이터를 Health Connect에서 가져오지 못했습니다. Health Connect 권한과 Samsung Health 데이터 연동 상태를 확인해주세요.",
                  data: {
                    hc,
                    usedFallback: {
                      height: false,
                      weight: false,
                    },
                  },
                });
                return;
              }

              const usedFallback = {
                height:
                  healthConnectHeightCm === null &&
                  toPositiveNumberOrNull(fallback_height_cm) !== null,
                weight:
                  healthConnectWeightKg === null &&
                  toPositiveNumberOrNull(fallback_weight_kg) !== null,
              };

              console.log("[HEALTH_SYNC_AND_SAVE]", {
                historyDays,
                healthConnectHeightCm,
                healthConnectWeightKg,
                fallback_height_cm,
                fallback_weight_kg,
                savedHeightCm: heightCm,
                savedWeightKg: weightKg,
                usedFallback,
                heightMeta: hc?.height ?? null,
                weightMeta: hc?.weight ?? null,
              });

              const res = await fetch(`${API_BASE_URL}/healthcare/sync`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                  height_cm: heightCm,
                  weight_kg: weightKg,
                  steps_today: hc?.stepsToday ?? 0,
                  gender,
                  goal,
                  source: "HealthConnect",
                }),
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "HC_SYNC_AND_SAVE_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const saved = await res.json();

              let history: {
                attempted: boolean;
                ok: boolean;
                error?: string;
                data?: any;
              } = {
                attempted: false,
                ok: true,
              };

              if (Array.isArray(hc?.dailySteps) && hc.dailySteps.length > 0) {
                history.attempted = true;

                const historyRes = await fetch(
                  `${API_BASE_URL}/healthcare/sync-history`,
                  {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      Authorization: `Bearer ${token}`,
                    },
                    body: JSON.stringify({
                      source: "HealthConnect",
                      daily_steps: hc.dailySteps,
                    }),
                  },
                );

                if (!historyRes.ok) {
                  const historyErr = await safeErrorMessage(historyRes);
                  history = {
                    attempted: true,
                    ok: false,
                    error: historyErr,
                  };
                } else {
                  let historyData: any = null;
                  try {
                    historyData = await historyRes.json();
                  } catch {
                    historyData = null;
                  }

                  history = {
                    attempted: true,
                    ok: true,
                    data: historyData,
                  };
                }
              }

              await AsyncStorage.setItem(scopedFirstSyncKey, "true");
              await AsyncStorage.removeItem(LEGACY_HEALTH_FIRST_SYNCED_KEY);

              sendToWeb({
                type: "HC_SYNC_AND_SAVE_RESULT",
                requestId,
                ok: true,
                partialSuccess: history.attempted && !history.ok,
                warning:
                  history.attempted && !history.ok
                    ? `기본 건강 데이터 저장은 성공했지만, 걸음수 히스토리 저장은 실패했습니다: ${history.error}`
                    : undefined,
                data: {
                  hc,
                  saved,
                  history,
                  usedFallback,
                },
              });
              return;
            }

            if (msg.type === "INBODY_MANUAL_SAVE_REQUEST") {
              const { requestId, payload } = msg;
              const { token, height, weight, gender, goal } = payload;

              const res = await fetch(`${API_BASE_URL}/healthcare/manual`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({ height, weight, gender, goal }),
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "INBODY_MANUAL_SAVE_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();

              sendToWeb({
                type: "INBODY_MANUAL_SAVE_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "HEALTHCARE_LATEST_REQUEST") {
              const { requestId, payload } = msg;
              const { token } = payload;

              const res = await fetch(`${API_BASE_URL}/healthcare/latest`, {
                method: "GET",
                headers: {
                  Authorization: `Bearer ${token}`,
                },
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "HEALTHCARE_LATEST_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "HEALTHCARE_LATEST_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "HEALTHCARE_UNLINK_REQUEST") {
              const { requestId, payload } = msg;
              const { token } = payload;
              const userKey = getStorageUserKey(payload);
              const scopedFirstSyncKey = getHealthFirstSyncedKey(userKey);

              const res = await fetch(`${API_BASE_URL}/healthcare/unlink`, {
                method: "DELETE",
                headers: {
                  Authorization: `Bearer ${token}`,
                },
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "HEALTHCARE_UNLINK_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();

              await AsyncStorage.removeItem(scopedFirstSyncKey);
              await AsyncStorage.removeItem(LEGACY_HEALTH_FIRST_SYNCED_KEY);

              try {
                await cancelAllMissionTimerNotificationsForUser(userKey);
              } catch {
                // ignore
              }

              sendToWeb({
                type: "HEALTHCARE_UNLINK_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "HEALTHCARE_TARGET_WEIGHT_SAVE_REQUEST") {
              const { requestId, payload } = msg;
              const { token, targetWeight } = payload;

              const res = await fetch(
                `${API_BASE_URL}/healthcare/target-weight`,
                {
                  method: "PATCH",
                  headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                  },
                  body: JSON.stringify({
                    target_weight: targetWeight,
                  }),
                },
              );

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "HEALTHCARE_TARGET_WEIGHT_SAVE_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "HEALTHCARE_TARGET_WEIGHT_SAVE_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "HEALTHCARE_LATEST_FAST_REQUEST") {
              const { requestId, payload } = msg;
              const { token } = payload;

              const res = await fetch(
                `${API_BASE_URL}/healthcare/latest-fast`,
                {
                  method: "GET",
                  headers: {
                    Authorization: `Bearer ${token}`,
                  },
                },
              );

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "HEALTHCARE_LATEST_FAST_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "HEALTHCARE_LATEST_FAST_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "HEALTHCARE_AVERAGE_REQUEST") {
              const { requestId, payload } = msg;
              const { token } = payload;

              const res = await fetch(`${API_BASE_URL}/healthcare/average`, {
                method: "GET",
                headers: {
                  Authorization: `Bearer ${token}`,
                },
              });

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "HEALTHCARE_AVERAGE_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "HEALTHCARE_AVERAGE_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            if (msg.type === "HEALTHCARE_HISTORY_REQUEST") {
              const { requestId, payload } = msg;
              const { token, week_start, week_end } = payload;

              const params = new URLSearchParams();
              if (week_start) params.append("week_start", week_start);
              if (week_end) params.append("week_end", week_end);

              const res = await fetch(
                `${API_BASE_URL}/healthcare/history?${params.toString()}`,
                {
                  method: "GET",
                  headers: {
                    Authorization: `Bearer ${token}`,
                  },
                },
              );

              if (!res.ok) {
                const err = await safeErrorMessage(res);
                sendToWeb({
                  type: "HEALTHCARE_HISTORY_RESULT",
                  requestId,
                  ok: false,
                  error: err,
                });
                return;
              }

              const data = await res.json();
              sendToWeb({
                type: "HEALTHCARE_HISTORY_RESULT",
                requestId,
                ok: true,
                data,
              });
              return;
            }

            console.log("ℹ️ Unknown message:", msg);
          } catch (e: any) {
            let requestId: string | undefined;

            try {
              const raw = event.nativeEvent.data;
              const msg = JSON.parse(raw || "{}");
              requestId = msg?.requestId;
            } catch {}

            sendToWeb({
              type: "RN_ERROR",
              requestId,
              ok: false,
              error: e?.message ? String(e.message) : String(e),
            });
          }
        }}
      />
    </SafeAreaView>
  );
}
