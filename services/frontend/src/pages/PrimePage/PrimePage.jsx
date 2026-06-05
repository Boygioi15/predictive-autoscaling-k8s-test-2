import React from "react";
import PrimeRangeCard from "./PrimeRangeCard";
import PrimeKthCard from "./PrimeKthCard";
import PrimeCheckCard from "./PrimeCheckCard";

const PrimePage = () => {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">CPU oriented task</h2>
        <p className="text-muted-foreground">
          Heavy arithmetic workloads for testing CPU saturation and CPU-based
          Auto-scale behavior.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <PrimeRangeCard />
        <PrimeKthCard />
        <PrimeCheckCard />
      </div>
    </div>
  );
};

export default PrimePage;
