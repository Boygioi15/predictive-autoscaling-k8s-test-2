import React from "react";
import TextAnalyzeCard from "./TextAnalyzeCard";
import TextPressureCard from "./TextPressureCard";
import TextTransformCard from "./TextTransformCard";

const TextPage = () => {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Memory oriented task</h2>
        <p className="text-muted-foreground">
          Includes text utilities and the memory-pressure API for RAM-oriented
          workload testing.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <TextAnalyzeCard />
        <TextTransformCard />
        <TextPressureCard />
      </div>
    </div>
  );
};

export default TextPage;
