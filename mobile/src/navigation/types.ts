import { NavigatorScreenParams } from "@react-navigation/native";

export type BottomTabParamList = {
  AssignmentsTab: undefined;
  HistoryTab: undefined;
  CommunicationsTab: undefined;
  ProfileTab: undefined;
};

export type RootStackParamList = {
  Login: undefined;
  Register: {
    token: string;
    email: string;
  };
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
