import { NavigatorScreenParams } from "@react-navigation/native";

export type BottomTabParamList = {
  AssignmentsTab: undefined;
  HistoryTab: undefined;
  CommunicationsTab: undefined;
  ProfileTab: undefined;
};

export type RootStackParamList = {
  Login:
    | {
        message?: string;
      }
    | undefined;
  Register: {
    token: string;
    email: string;
  };
  ForgotPassword:
    | {
        token?: string;
      }
    | undefined;
  MainTabs: NavigatorScreenParams<BottomTabParamList>;
  ScenarioPicker: {
    isFirstTimer?: boolean;
  };
  PreSession: {
    assignmentId?: string;
    scenarioId: string;
    isFirstSession?: boolean;
  };
  Session: {
    assignmentId?: string;
    scenarioId: string;
    sessionId: string;
    isFirstSession?: boolean;
  };
  Score: {
    sessionId: string;
    isFirstDrill?: boolean;
  };
  MessageThread: {
    threadId: string;
  };
  NewMessage: undefined;
};
