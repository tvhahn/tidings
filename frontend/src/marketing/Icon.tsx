import {
  ArrowRight,
  BookOpen,
  Check,
  Clock,
  Code2,
  Feather,
  Fuel,
  Heart,
  Landmark,
  Lock,
  Mail,
  Plus,
  Repeat,
  Server,
  ShoppingCart,
  Sparkles,
  TrendingDown,
  Utensils,
  Zap,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  "arrow-right": ArrowRight,
  "book-open": BookOpen,
  check: Check,
  clock: Clock,
  "code-2": Code2,
  feather: Feather,
  fuel: Fuel,
  heart: Heart,
  landmark: Landmark,
  lock: Lock,
  mail: Mail,
  plus: Plus,
  repeat: Repeat,
  server: Server,
  "shopping-cart": ShoppingCart,
  sparkles: Sparkles,
  "trending-down": TrendingDown,
  utensils: Utensils,
  zap: Zap,
};

interface Props {
  name: string;
  size?: number;
  className?: string;
}

export function Icon({ name, size = 16, className }: Props) {
  const C = ICONS[name];
  if (!C) {
    if (import.meta.env.DEV) {
      // Hint for missing icon mappings during the marketing port.
      console.warn(`Marketing Icon: unknown name "${name}"`);
    }
    return null;
  }
  return <C size={size} strokeWidth={1.75} className={className} aria-hidden="true" />;
}
