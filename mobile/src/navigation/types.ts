import { NavigatorScreenParams } from "@react-navigation/native";

export type BottomTabParamList = {
  AssignmentsTab: undefined;
  HistoryTab: undefined;
  CommunicationsTab: undefined;
  ProfileTab: undefined;
};

export type RootStackParamList = {
  Login: undefined;
  MainTabs: NavigatorScreenParams<BottomTabParamList>;
  PreSession: {
    assignmentId?: string;
    scenarioId: string;
  };
  Session: {
    assignmentId?: string;
    scenarioId: string;
    sessionId: string;
  };
  Score: {
    sessionId: string;
  };
  MessageThread: {
    threadId: string;
  };
  NewMessage: undefined;
};
