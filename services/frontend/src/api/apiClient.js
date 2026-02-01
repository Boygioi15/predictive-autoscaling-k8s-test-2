import axios from "axios";

export const axiosClient_Prime = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:3000",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 10000,
});
//logger
axiosClient_Prime.interceptors.response.use(
  (response) => {
    console.log("📥 [Response]", {
      url: response.config.url,
      status: response.status,
      data: response.data,
    });
    return response;
  },
  async (error) => {
    /////LOGGER BLOCK!
    if (error.code === "ECONNABORTED") {
      console.error("⏰ Request timed out");
    } else if (error.response) {
      console.error("❌ [Error Response]", {
        status: error.response.status,
        data: error.response.data,
      });
    } else {
      console.error("🚨 [Error]", error);
    }

    return Promise.reject(error);
  },
);
axiosClient_Prime.interceptors.request.use((config) => {
  console.log("Request", {
    url: config.url,
    method: config.method,
    headers: config.headers,
    data: config.data,
  });
  return config;
});

export const axiosClient_Text = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:3001",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 10000,
});
//logger
axiosClient_Text.interceptors.response.use(
  (response) => {
    console.log("📥 [Response]", {
      url: response.config.url,
      status: response.status,
      data: response.data,
    });
    return response;
  },
  async (error) => {
    /////LOGGER BLOCK!
    if (error.code === "ECONNABORTED") {
      console.error("⏰ Request timed out");
    } else if (error.response) {
      console.error("❌ [Error Response]", {
        status: error.response.status,
        data: error.response.data,
      });
    } else {
      console.error("🚨 [Error]", error);
    }

    return Promise.reject(error);
  },
);
axiosClient_Text.interceptors.request.use((config) => {
  console.log("Request", {
    url: config.url,
    method: config.method,
    headers: config.headers,
    data: config.data,
  });
  return config;
});

export const axiosClient_IO = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:3002",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 10000,
});
//logger
axiosClient_IO.interceptors.response.use(
  (response) => {
    console.log("📥 [Response]", {
      url: response.config.url,
      status: response.status,
      data: response.data,
    });
    return response;
  },
  async (error) => {
    /////LOGGER BLOCK!
    if (error.code === "ECONNABORTED") {
      console.error("⏰ Request timed out");
    } else if (error.response) {
      console.error("❌ [Error Response]", {
        status: error.response.status,
        data: error.response.data,
      });
    } else {
      console.error("🚨 [Error]", error);
    }

    return Promise.reject(error);
  },
);
axiosClient_IO.interceptors.request.use((config) => {
  console.log("Request", {
    url: config.url,
    method: config.method,
    headers: config.headers,
    data: config.data,
  });
  return config;
});
