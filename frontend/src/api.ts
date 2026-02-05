import axios from "axios";

const BACKEND_PORT = "8021";

export const resolveApiBaseUrl = () => {
  const envBase = import.meta.env.VITE_API_BASE_URL;
  if (envBase && String(envBase).trim()) {
    return String(envBase).trim();
  }
  if (typeof window !== "undefined" && window.location) {
    const { protocol, hostname, origin, port } = window.location;
    if (port === BACKEND_PORT) {
      return origin || `${protocol}//${hostname}:${BACKEND_PORT}`;
    }
    if (hostname) {
      return `${protocol}//${hostname}:${BACKEND_PORT}`;
    }
  }
  return `http://localhost:${BACKEND_PORT}`;
};

export const apiBaseUrl = resolveApiBaseUrl();
export const LONG_API_TIMEOUT = 600000;

export const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000,
});

export const apiLong = axios.create({
  baseURL: apiBaseUrl,
  timeout: LONG_API_TIMEOUT,
});
