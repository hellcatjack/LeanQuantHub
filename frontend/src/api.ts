import axios from "axios";

const resolveBaseURL = () => {
  const envBase = import.meta.env.VITE_API_BASE_URL;
  if (envBase && String(envBase).trim()) {
    return envBase;
  }
  if (typeof window !== "undefined" && window.location) {
    const { protocol, hostname } = window.location;
    return `${protocol}//${hostname}:8021`;
  }
  return "http://localhost:8021";
};

const baseURL = resolveBaseURL();

export const api = axios.create({
  baseURL,
  timeout: 10000,
});
