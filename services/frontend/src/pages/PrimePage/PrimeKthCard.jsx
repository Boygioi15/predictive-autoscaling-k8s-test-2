import React, { useState } from "react";
import { toast } from "sonner";
import { Search, Clock, Hash } from "lucide-react";
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

// Giả sử import SpinnerOverlay và primeApi

const PrimeKthCard = () => {
  const [kInput, setKInput] = useState(0);
  const [kResult, setKResult] = useState(null);
  const [kMetrics, setKMetrics] = useState(null);
  const [kWaiting, setKWaiting] = useState(false);

  const getKthResult = async () => {
    if (!kInput || kInput <= 0) {
      toast.error("Vui lòng nhập vị trí K lớn hơn 0");
      return;
    }

    try {
      setKWaiting(true);
      setKResult(null);
      setKMetrics(null);

      // Gọi API: /prime/kth?k=...
      const response = await primeApi.getKthPrime(kInput);

      // Giả sử API trả về: { result: 3571, timeTaken: "15ms" }
      setKResult(response.data.result);
      setKMetrics({
        timeTaken: response.data.timeTaken,
      });
    } catch (error) {
      toast.error("Lỗi khi tìm số thứ K");
      console.error(error);
    } finally {
      setKWaiting(false);
    }
  };

  return (
    <Card className="flex flex-col relative h-full">
      {kWaiting && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center rounded-lg">
          <span className="animate-spin text-primary text-2xl">⏳</span>
        </div>
      )}

      <CardHeader>
        <div className="flex items-center gap-2">
          <Search className="w-5 h-5 text-orange-500" />
          <CardTitle>Tìm số thứ K</CardTitle>
        </div>
        <CardDescription>Tìm số nguyên tố nằm ở vị trí thứ K.</CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 flex-1">
        <div className="space-y-2">
          <Label htmlFor="k-th">Nhập vị trí (K)</Label>
          <Input
            id="k-th"
            type="number"
            placeholder="VD: 500"
            value={kInput}
            onChange={(e) => setKInput(Number(e.target.value))}
            disabled={kWaiting}
          />
        </div>

        <div className="rounded-md bg-muted/50 text-sm min-h-[6rem] p-3 flex flex-col justify-center">
          {kResult === null ? (
            <div className="text-muted-foreground text-center">Kết quả...</div>
          ) : (
            <div className="space-y-3 animate-in fade-in zoom-in duration-300">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-medium">
                  <Hash className="w-4 h-4 text-orange-600" />
                  <span>Kết quả:</span>
                </div>
                <span className="text-orange-600 font-bold text-lg">
                  {kResult.toLocaleString()}
                </span>
              </div>

              {kMetrics && (
                <div className="flex items-center justify-between text-xs text-muted-foreground border-t pt-2 border-slate-200 dark:border-slate-700">
                  <div className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    <span>Time taken:</span>
                  </div>
                  <span className="font-mono font-semibold text-foreground">
                    {kMetrics.timeTaken}
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
          variant="secondary"
          onClick={getKthResult}
          disabled={kWaiting}
        >
          {kWaiting ? "Đang tìm..." : "Tìm kiếm"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default PrimeKthCard;
