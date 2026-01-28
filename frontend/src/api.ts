import axios from "axios";

export const resolveApiBaseUrl = () => {
  const envBase = import.meta.env.VITE_API_BASE_URL;
  if (envBase && String(envBase).trim()) {
    return String(envBase).trim();
  }
  if (typeof window !== "undefined" && window.location) {
    return window.location.origin || `${window.location.protocol}//${window.location.host}`;
  }
  return "http://localhost:8021";
};

export const apiBaseUrl = resolveApiBaseUrl();

export const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000,
});
