import { axiosClient_IO } from "./apiClient";

const ioApi = {
  readFile: async ({ fileId, sizeKb, holdMs }) => {
    return await axiosClient_IO.get(
      `/io/read?fileId=${encodeURIComponent(fileId)}&sizeKb=${sizeKb}&holdMs=${holdMs}`,
    );
  },
  writeFile: async ({ fileId, sizeKb, segments, holdMs }) => {
    return await axiosClient_IO.post(
      `/io/write?fileId=${encodeURIComponent(fileId)}&sizeKb=${sizeKb}&segments=${segments}&holdMs=${holdMs}`,
    );
  },
};

export default ioApi;
