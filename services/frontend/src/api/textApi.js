import { axiosClient_Text } from "./apiClient";

const textApi = {
  analyzeText: async (text) => {
    return await axiosClient_Text.post("/text/analyze", { text });
  },
  transformText: async (text, rounds) => {
    return await axiosClient_Text.post(`/text/transform?rounds=${rounds}`, {
      text,
    });
  },
  createMemoryPressure: async ({
    text,
    chunkSizeKb,
    chunkCount,
    holdMs,
  }) => {
    return await axiosClient_Text.post(
      `/text/pressure?chunkSizeKb=${chunkSizeKb}&chunkCount=${chunkCount}&holdMs=${holdMs}`,
      { text },
    );
  },
};
export default textApi;
