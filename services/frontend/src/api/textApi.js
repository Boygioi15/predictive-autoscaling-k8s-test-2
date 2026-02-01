import { axiosClient_Text } from "./apiClient";

const textApi = {
  analyzeText: async (text) => {
    return await axiosClient_Text.post("/text/analyze", { text });
  },
  transformText: async (text, rounds) => {
    return await axiosClient_Text.post(`/text/transform?round=${rounds}`, {
      text,
    });
  },
};
export default textApi;
