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
  const [checkResult, setCheckResult] = useState(null);
  const [checkWaiting, setCheckWaiting] = useState(false);

  const handleCheck = async () => {
    if (!checkInput || checkInput <= 0) {
      toast.error("Please enter an N greater than 0");
      return;
    }

    try {
      setCheckWaiting(true);
      setCheckResult(null);

      const response = await primeApi.checkPrime(checkInput);

      setCheckResult(response.data);
    } catch (error) {
      toast.error("Failed to check the number");
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
          <CardTitle>Prime check</CardTitle>
        </div>
        <CardDescription>
          Check whether any given N is a prime number.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="space-y-2">
          <Label htmlFor="check-n">Number to check (N)</Label>
          <Input
            id="check-n"
            type="number"
            placeholder="e.g. 9999991"
            value={checkInput}
            onChange={(e) => setCheckInput(Number(e.target.value))}
            disabled={checkWaiting}
          />
        </div>

        <div className="flex min-h-[8rem] flex-1 flex-col rounded-md bg-muted/50 p-3 text-sm">
          {checkResult === null ? (
            <div className="flex h-full flex-1 items-center justify-center gap-2 text-center text-muted-foreground">
              <HelpCircle className="w-4 h-4" /> Prime / Composite
            </div>
          ) : (
            <div className="animate-in fade-in zoom-in duration-300 text-center">
              {checkResult.isPrime ? (
                <div className="flex flex-col items-center gap-1 text-green-600">
                  <CheckCircle2 className="w-8 h-8 mb-1" />
                  <span className="font-bold text-lg">PRIME</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1 text-red-500">
                  <XCircle className="w-8 h-8 mb-1" />
                  <span className="font-bold text-lg">NOT PRIME</span>
                </div>
              )}
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
          {checkWaiting ? "Checking..." : "Check now"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default PrimeCheckCard;
