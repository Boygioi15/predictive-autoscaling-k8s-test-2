import React, { useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, XCircle, HelpCircle } from "lucide-react";
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

const PrimeCheckCard = () => {
  const [checkInput, setCheckInput] = useState(0);
  const [checkResult, setCheckResult] = useState(null); // Object: { isPrime: true/false, message: "..." }
  const [checkWaiting, setCheckWaiting] = useState(false);

  const handleCheck = async () => {
    if (!checkInput || checkInput <= 0) {
      toast.error("Vui lòng nhập số N lớn hơn 0");
      return;
    }

    try {
      setCheckWaiting(true);
      setCheckResult(null);

      // Gọi API: /prime/check?n=...
      const response = await primeApi.checkPrime(checkInput);

      // API trả về: { isPrime: boolean, message: string }
      setCheckResult(response.data);
    } catch (error) {
      toast.error("Lỗi khi kiểm tra số");
      console.error(error);
    } finally {
      setCheckWaiting(false);
    }
  };

  return (
    <Card className="flex flex-col relative h-full">
      {checkWaiting && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center rounded-lg">
          <span className="animate-spin text-primary text-2xl">⏳</span>
        </div>
      )}

      <CardHeader>
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-green-500" />
          <CardTitle>Kiểm tra (Check)</CardTitle>
        </div>
        <CardDescription>
          Kiểm tra một số N bất kỳ có phải là số nguyên tố không.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 flex-1">
        <div className="space-y-2">
          <Label htmlFor="check-n">Nhập số cần kiểm tra (N)</Label>
          <Input
            id="check-n"
            type="number"
            placeholder="VD: 9999991"
            value={checkInput}
            onChange={(e) => setCheckInput(Number(e.target.value))}
            disabled={checkWaiting}
          />
        </div>

        <div className="rounded-md bg-muted/50 text-sm min-h-[6rem] p-3 flex flex-col justify-center items-center">
          {checkResult === null ? (
            <div className="text-muted-foreground flex gap-2 items-center">
              <HelpCircle className="w-4 h-4" /> True / False
            </div>
          ) : (
            <div className="text-center animate-in fade-in zoom-in duration-300">
              {checkResult.isPrime ? (
                <div className="flex flex-col items-center gap-1 text-green-600">
                  <CheckCircle2 className="w-8 h-8 mb-1" />
                  <span className="font-bold text-lg">LÀ SỐ NGUYÊN TỐ</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1 text-red-500">
                  <XCircle className="w-8 h-8 mb-1" />
                  <span className="font-bold text-lg">KHÔNG PHẢI</span>
                </div>
              )}
              {/* Hiển thị message chi tiết từ server nếu cần */}
              <p className="text-xs text-muted-foreground mt-2 border-t pt-2 w-full">
                {checkResult.message}
              </p>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          variant="outline"
          onClick={handleCheck}
          disabled={checkWaiting}
        >
          {checkWaiting ? "Đang kiểm tra..." : "Kiểm tra ngay"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default PrimeCheckCard;
