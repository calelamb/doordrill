import * as Linking from "expo-linking";

import { RootStackParamList } from "../navigation/types";
import { navigationRef } from "./notifications";

type InviteRouteParams = RootStackParamList["Register"];

let pendingInviteParams: InviteRouteParams | null = null;

function canNavigateToRegister(): boolean {
  const state = navigationRef.getRootState();
  return Boolean(state?.routeNames.includes("Register"));
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

function parseInviteUrl(url: string): InviteRouteParams | null {
  const parsed = Linking.parse(url);
  const route = (parsed.path || parsed.hostname || "").replace(/^\/+|\/+$/g, "");
  const token = typeof parsed.queryParams?.token === "string" ? parsed.queryParams.token : null;
  const email = typeof parsed.queryParams?.email === "string" ? parsed.queryParams.email : "";

  if (route !== "invite" || !token) {
    return null;
  }

  return { token, email };
}

export function handleInviteUrl(url: string): boolean {
  const params = parseInviteUrl(url);
  if (!params) {
    return false;
  }
  return navigateToInvite(params);
}

export async function primeInitialInviteUrl(): Promise<void> {
  const initialUrl = await Linking.getInitialURL();
  if (initialUrl) {
    handleInviteUrl(initialUrl);
  }
}

export function setupInviteLinkListener(): () => void {
  const subscription = Linking.addEventListener("url", ({ url }) => {
    handleInviteUrl(url);
  });

  return () => {
    subscription.remove();
  };
}

export function flushPendingInviteNavigation(): boolean {
  if (!pendingInviteParams) {
    return false;
  }
  return navigateToInvite(pendingInviteParams);
}
