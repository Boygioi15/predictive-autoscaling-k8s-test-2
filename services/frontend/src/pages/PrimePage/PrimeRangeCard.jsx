import React, { useState } from "react";
import { toast } from "sonner"; // Hoặc thư viện toast bạn đang dùng
import { Calculator, Clock, CheckCircle2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import primeApi from "@/api/primeApi";

// Giả sử bạn import SpinnerOverlay và primeApi từ nơi khác
// import SpinnerOverlay from "@/components/SpinnerOverlay";
// import primeApi from "@/apis/primeApi";

const PrimeRangeCard = () => {
  const [rangeInput, setRangeInput] = useState(0);
  const [rangeResult, setRangeResult] = useState(null); // Lưu kết quả số lượng
  const [rangeMetrics, setRangeMetrics] = useState(null); // Lưu thông số thời gian (timeTaken)
  const [rangeWaiting, setRangeWaiting] = useState(false);

  const getRangeResult = async () => {
    // Validate input đơn giản
    if (!rangeInput || rangeInput <= 0) {
      toast.error("Vui lòng nhập số N lớn hơn 0");
      return;
    }

    try {
      setRangeWaiting(true);
      setRangeResult(null); // Reset kết quả cũ
      setRangeMetrics(null); // Reset metrics cũ

      // Gọi API
      const response = await primeApi.getTotalPrimeInRange(rangeInput);

      // Giả sử API trả về: { totalPrimesFound: 123, timeTaken: "45ms" }
      // Lưu ý: response.data tùy thuộc vào config axios của bạn
      setRangeResult(response.data.totalPrimesFound);
      setRangeMetrics({
        timeTaken: response.data.timeTaken,
      });
    } catch (error) {
      toast.error("Có lỗi khi lấy dữ liệu số nguyên tố");
      console.error(error);
    } finally {
      setRangeWaiting(false);
    }
  };

  return (
    <Card className="flex flex-col relative h-full">
      {/* Spinner Loading */}
      {rangeWaiting && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center rounded-lg">
          {/* Thay bằng SpinnerOverlay của bạn */}
          <span className="animate-spin text-primary">⏳</span>
        </div>
      )}

      <CardHeader>
        <div className="flex items-center gap-2">
          <Calculator className="w-5 h-5 text-blue-500" />
          <CardTitle>Sàng Eratosthenes</CardTitle>
        </div>
        <CardDescription>
          Đếm số lượng số nguyên tố trong khoảng từ 1 đến N.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 flex-1">
        <div className="space-y-2">
          <Label htmlFor="range-n">Nhập giới hạn (N)</Label>
          <Input
            id="range-n"
            type="number"
            placeholder="VD: 100000"
            value={rangeInput}
            onChange={(e) => setRangeInput(Number(e.target.value))}
            disabled={rangeWaiting}
          />
        </div>

        {/* Khu vực hiển thị kết quả */}
        <div className="rounded-md bg-muted/50 text-sm min-h-[6rem] p-3 flex flex-col justify-center">
          {rangeResult === null ? (
            <div className="text-muted-foreground text-center">
              Kết quả sẽ hiện ở đây...
            </div>
          ) : (
            <div className="space-y-3 animate-in fade-in zoom-in duration-300">
              {/* Dòng 1: Kết quả số lượng */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-medium">
                  <CheckCircle2 className="w-4 h-4 text-green-600" />
                  <span>Tìm thấy:</span>
                </div>
                <span className="text-green-600 font-bold text-lg">
                  {rangeResult.toLocaleString()} số
                </span>
              </div>

              {/* Dòng 2: Thời gian xử lý (Metrics) */}
              {rangeMetrics && (
                <div className="flex items-center justify-between text-xs text-muted-foreground border-t pt-2 border-slate-200 dark:border-slate-700">
                  <div className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    <span>CPU Time:</span>
                  </div>
                  <span className="font-mono font-semibold text-foreground">
                    {rangeMetrics.timeTaken}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          onClick={getRangeResult}
          disabled={rangeWaiting}
        >
          {rangeWaiting ? "Đang tính toán..." : "Bắt đầu tính"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default PrimeRangeCard;
