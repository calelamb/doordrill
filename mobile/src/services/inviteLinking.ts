import * as Linking from "expo-linking";

import { RootStackParamList } from "../navigation/types";
import { navigationRef } from "./notifications";

type InviteRouteParams = RootStackParamList["Register"];
type ForgotPasswordRouteParams = RootStackParamList["ForgotPassword"];

let pendingInviteParams: InviteRouteParams | null = null;
let pendingForgotPasswordParams: ForgotPasswordRouteParams | null = null;
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function canNavigateToRegister(): boolean {
  const state = navigationRef.getRootState();
  return Boolean(state?.routeNames.includes("Register"));
}

function canNavigateToForgotPassword(): boolean {
  const state = navigationRef.getRootState();
  return Boolean(state?.routeNames.includes("ForgotPassword"));
}

function navigateToInvite(params: InviteRouteParams): boolean {
  if (!navigationRef.isReady() || !canNavigateToRegister()) {
    pendingInviteParams = params;
    return false;
  }

  navigationRef.navigate("Register", params);
  pendingInviteParams = null;
  return true;
}

function navigateToForgotPassword(params: ForgotPasswordRouteParams): boolean {
  if (!navigationRef.isReady() || !canNavigateToForgotPassword()) {
    pendingForgotPasswordParams = params;
    return false;
  }

  navigationRef.navigate("ForgotPassword", params);
  pendingForgotPasswordParams = null;
  return true;
}

function parseAuthUrl(url: string):
  | {
      route: "invite";
      params: InviteRouteParams;
    }
  | {
      route: "reset-password";
      params: ForgotPasswordRouteParams;
    }
  | null {
  const parsed = Linking.parse(url);
  const route = (parsed.path || parsed.hostname || "").replace(/^\/+|\/+$/g, "");
  const token = typeof parsed.queryParams?.token === "string" ? parsed.queryParams.token : null;
  if (route === "reset-password" && token) {
    return {
      route: "reset-password",
      params: { token },
    };
  }

  if (route !== "invite" || !token) {
    return null;
  }

  const rawEmail = typeof parsed.queryParams?.email === "string" ? parsed.queryParams.email : "";
  const email = rawEmail.length <= 254 && EMAIL_REGEX.test(rawEmail) ? rawEmail : "";
  return {
    route: "invite",
    params: { token, email },
  };
}

export function handleAuthUrl(url: string): boolean {
  const destination = parseAuthUrl(url);
  if (!destination) {
    return false;
  }

  if (destination.route === "reset-password") {
    return navigateToForgotPassword(destination.params);
  }

  return navigateToInvite(destination.params);
}

export async function primeInitialAuthUrl(): Promise<void> {
  const initialUrl = await Linking.getInitialURL();
  if (initialUrl) {
    handleAuthUrl(initialUrl);
  }
}

export function setupAuthLinkListener(): () => void {
  const subscription = Linking.addEventListener("url", ({ url }) => {
    handleAuthUrl(url);
  });

  return () => {
    subscription.remove();
  };
}

export function flushPendingAuthLinkNavigation(): boolean {
  if (!pendingInviteParams) {
    if (!pendingForgotPasswordParams) {
      return false;
    }
    return navigateToForgotPassword(pendingForgotPasswordParams);
  }
  return navigateToInvite(pendingInviteParams);
}
