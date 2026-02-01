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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { FileText, HelpCircle, Repeat } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
const TextTransformCard = () => {
  const [text, setText] = useState("");
  const [rounds, setRounds] = useState(50);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleTransform = async () => {
    if (!text || text.length === 0) {
      toast.error("Vui lòng nhập văn bản");
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      const response = await textApi.transformText(text, rounds);
      setResult(response.data);
    } catch (err) {
      toast.error("Lỗi khi xử lý văn bản");
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
          <Repeat className="w-5 h-5 text-purple-500" />
          <CardTitle>Biến đổi văn bản</CardTitle>
        </div>
        <CardDescription>
          Đảo chuỗi & xử lý lặp nhiều vòng để tạo CPU load.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 flex-1">
        <div className="space-y-2">
          <Label>Văn bản</Label>
          <Input
            placeholder="VD: Hello World"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={loading}
          />
        </div>

        <div className="space-y-2">
          <Label>Số vòng xử lý (rounds)</Label>
          <Input
            type="number"
            value={rounds}
            onChange={(e) => setRounds(Number(e.target.value))}
            disabled={loading}
          />
        </div>

        <div className="rounded-md bg-muted/50 text-sm min-h-[6rem] p-3 flex flex-col justify-center">
          {result === null ? (
            <div className="text-muted-foreground flex gap-2 items-center justify-center">
              <HelpCircle className="w-4 h-4" /> Chưa có kết quả
            </div>
          ) : (
            <div className="animate-in fade-in zoom-in duration-300 space-y-1">
              <div>
                📏 Độ dài input: <b>{result.originalLength}</b>
              </div>
              <div>
                🔁 Số vòng: <b>{result.rounds}</b>
              </div>
              <div>
                ⏱ Thời gian: <b>{result.timeTaken}</b>
              </div>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          variant="outline"
          onClick={handleTransform}
          disabled={loading}
        >
          {loading ? "Đang xử lý..." : "Thực hiện"}
        </Button>
      </CardFooter>
    </Card>
  );
};
export default TextTransformCard;
