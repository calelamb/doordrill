export type RootStackParamList = {
  Login: undefined;
  Assignments: undefined;
  PreSession: {
    assignmentId: string;
    scenarioId: string;
  };
  Session: {
    assignmentId: string;
    scenarioId: string;
    sessionId: string;
  };
  Score: {
    sessionId: string;
  };
  History: undefined;
};
