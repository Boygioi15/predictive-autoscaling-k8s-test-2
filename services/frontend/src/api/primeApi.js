import { axiosClient_Prime } from "./apiClient";

const primeApi = {
  getTotalPrimeInRange: async (range) => {
    return await axiosClient_Prime.get(`/range?n=${range}`);
  },
  getKthPrime: async (k) => {
    return await axiosClient_Prime.get(`/kth?k=${k}`);
  },
  checkPrime: async (n) => {
    return await axiosClient_Prime.get(`/check?n=${n}`);
  },
};
export default primeApi;
