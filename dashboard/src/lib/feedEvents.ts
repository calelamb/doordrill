export const FEED_REFRESH_EVENT = "doordrill:feed-refresh";
export const LEGACY_FEED_REFRESH_EVENT = "manager-feed:refresh";

export function dispatchFeedRefresh(): void {
  window.dispatchEvent(new CustomEvent(FEED_REFRESH_EVENT));
  window.dispatchEvent(new Event(LEGACY_FEED_REFRESH_EVENT));
}
