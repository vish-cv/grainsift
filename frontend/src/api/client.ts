import axios from "axios";

export const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    const msg =
      err.response?.data?.detail ?? err.message ?? "Unknown error";
    return Promise.reject(new Error(msg));
  }
);
