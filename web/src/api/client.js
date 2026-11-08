import axios from "axios";

// Central HTTP client: single place for baseURL, API key and error unwrap.
const client = axios.create({
  baseURL: "/api/v1",
  timeout: 30_000,
});

const apiKey = import.meta.env.VITE_API_KEY || "";
if (apiKey) {
  client.interceptors.request.use((config) => {
    config.headers["X-API-Key"] = apiKey;
    return config;
  });
}

// Unwrap axios errors into the backend error envelope {error, detail}.
client.interceptors.response.use(
  (response) => response.data,
  (err) => {
    const payload = err.response?.data ?? { error: "network_error", detail: err.message };
    return Promise.reject(payload);
  },
);

export default client;
