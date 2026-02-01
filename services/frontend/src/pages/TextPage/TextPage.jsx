import React from "react";
import { Button } from "@/components/ui/button";
import TextAnalyzeCard from "./TextAnalyzeCard";
import TextTransformCard from "./TextTransformCard";

const TextPage = () => {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Xử lý text</h2>
        <p className="text-muted-foreground">
          Xử lý chuỗi văn bản lớn để tiêu tốn RAM.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Block 1: Phân tích text */}
        <TextAnalyzeCard />

        {/* Block 2: Biến đổi text */}
        <TextTransformCard />
      </div>
    </div>
  );
};

export default TextPage;
