import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Calculator, Search, CheckCircle2 } from "lucide-react";
import primeApi from "@/api/primeApi";
import { toast } from "sonner";
import SpinnerOverlay from "@/components/self/SpinnerOverlay";
import PrimeRangeCard from "./PrimeRangeCard";
import PrimeKthCard from "./PrimeKthCard";
import PrimeCheckCard from "./PrimeCheckCard";

const PrimePage = () => {
  return (
    <div className="space-y-6">
      {/* Tiêu đề chung */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight">
          CPU Intensive Tasks
        </h2>
        <p className="text-muted-foreground">
          Các tác vụ tính toán số học nặng để kiểm tra khả năng chịu tải của CPU
          (Auto-scaling based on CPU).
        </p>
      </div>

      {/* Grid Layout: 1 cột trên mobile, 3 cột trên desktop */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Block 1: Tìm số nguyên tố 1-N */}
        <PrimeRangeCard />

        {/* Block 2: Tìm số nguyên tố thứ K */}
        <PrimeKthCard />

        {/* Block 3: Kiểm tra tính nguyên tố */}
        <PrimeCheckCard />
      </div>
    </div>
  );
};

export default PrimePage;
