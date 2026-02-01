import { axiosClient_Prime } from "./apiClient";

const primeApi = {
  getTotalPrimeInRange: async (range) => {
    return await axiosClient_Prime.get(`/prime/range?n=${range}`);
  },
  getKthPrime: async (k) => {
    return await axiosClient_Prime.get(`/prime/kth?k=${k}`);
  },
  checkPrime: async (n) => {
    return await axiosClient_Prime.get(`/prime/check?n=${n}`);
  },
};
export default primeApi;
