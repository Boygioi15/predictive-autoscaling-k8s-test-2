import textApi from "@/api/textApi";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { FileText, HelpCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const TextAnalyzeCard = () => {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleAnalyze = async () => {
    if (!text) {
      toast.error("Vui lòng nhập văn bản dài hơn một chút");
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      const response = await textApi.analyzeText(text);
      setResult(response.data);
    } catch (err) {
      toast.error("Lỗi khi phân tích văn bản");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="flex flex-col relative h-full">
      {loading && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center rounded-lg">
          <span className="animate-spin text-primary text-2xl">⏳</span>
        </div>
      )}

      <CardHeader>
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-blue-500" />
          <CardTitle>Phân tích văn bản</CardTitle>
        </div>
        <CardDescription>
          Phân tích độ dài, từ vựng và tần suất xuất hiện.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 flex-1">
        <div className="space-y-2">
          <Label>Nhập văn bản</Label>
          <Textarea
            placeholder="Dán đoạn văn bản bất kỳ vào đây..."
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={loading}
            rows={4}
          />
        </div>

        <div className="rounded-md bg-muted/50 text-sm min-h-[8rem] p-3">
          {result === null ? (
            <div className="text-muted-foreground flex items-center gap-2 justify-center h-full">
              <HelpCircle className="w-4 h-4" />
              Chưa có kết quả
            </div>
          ) : (
            <div className="space-y-2 animate-in fade-in zoom-in duration-300">
              <div>
                📏 Ký tự: <b>{result.analysis.length}</b>
              </div>
              <div>
                🧩 Từ: <b>{result.analysis.totalWords}</b>
              </div>
              <div>
                📘 Từ duy nhất: <b>{result.analysis.uniqueWords}</b>
              </div>
              <div>
                ⏱ Thời gian: <b>{result.timeTaken}</b>
              </div>

              <div className="pt-2 border-t">
                <p className="font-semibold mb-1">Top từ phổ biến:</p>
                <ul className="text-xs space-y-1">
                  {result.analysis.topWords.map((w) => (
                    <li key={w.word}>
                      • {w.word} ({w.count})
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          variant="outline"
          onClick={handleAnalyze}
          disabled={loading}
        >
          {loading ? "Đang phân tích..." : "Phân tích"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default TextAnalyzeCard;
