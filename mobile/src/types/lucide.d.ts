import 'lucide-react-native';

declare module 'lucide-react-native' {
    export interface LucideProps {
        color?: string | undefined;
        size?: number | string | undefined;
        strokeWidth?: number | string | undefined;
        style?: any;
    }
}
