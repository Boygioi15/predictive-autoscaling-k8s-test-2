import React, { useState } from "react";
import { toast } from "sonner";
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

const PrimeRangeCard = () => {
  const [rangeInput, setRangeInput] = useState(0);
  const [rangeResult, setRangeResult] = useState(null);
  const [rangeMetrics, setRangeMetrics] = useState(null);
  const [rangeWaiting, setRangeWaiting] = useState(false);

  const getRangeResult = async () => {
    if (!rangeInput || rangeInput <= 0) {
      toast.error("Please enter an N greater than 0");
      return;
    }

    try {
      setRangeWaiting(true);
      setRangeResult(null);
      setRangeMetrics(null);

      const response = await primeApi.getTotalPrimeInRange(rangeInput);

      setRangeResult(response.data.totalPrimesFound);
      setRangeMetrics({
        timeTaken: response.data.timeTaken,
      });
    } catch (error) {
      toast.error("Failed to fetch prime data");
      console.error(error);
    } finally {
      setRangeWaiting(false);
    }
  };

  return (
    <Card className="flex flex-col relative h-full">
      {rangeWaiting && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center rounded-lg">
          <span className="animate-spin text-primary">⏳</span>
        </div>
      )}

      <CardHeader>
        <div className="flex items-center gap-2">
          <Calculator className="w-5 h-5 text-blue-500" />
          <CardTitle>Prime range count</CardTitle>
        </div>
        <CardDescription>
          Count prime numbers in the range from 1 to N.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="space-y-2">
          <Label htmlFor="range-n">Upper bound (N)</Label>
          <Input
            id="range-n"
            type="number"
            placeholder="e.g. 100000"
            value={rangeInput}
            onChange={(e) => setRangeInput(Number(e.target.value))}
            disabled={rangeWaiting}
          />
        </div>

        <div className="flex min-h-[8rem] flex-1 flex-col rounded-md bg-muted/50 p-3 text-sm">
          {rangeResult === null ? (
            <div className="flex h-full flex-1 items-center justify-center text-center text-muted-foreground">
              Results will appear here...
            </div>
          ) : (
            <div className="space-y-3 animate-in fade-in zoom-in duration-300">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-medium">
                  <CheckCircle2 className="w-4 h-4 text-green-600" />
                  <span>Found:</span>
                </div>
                <span className="text-green-600 font-bold text-lg">
                  {rangeResult.toLocaleString()} primes
                </span>
              </div>

              {rangeMetrics && (
                <div className="flex items-center justify-between text-xs text-muted-foreground border-t pt-2 border-slate-200 dark:border-slate-700">
                  <div className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    <span>Processing time:</span>
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
          {rangeWaiting ? "Calculating..." : "Start calculation"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default PrimeRangeCard;
