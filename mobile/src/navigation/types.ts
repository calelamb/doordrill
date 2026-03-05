export type RootStackParamList = {
  Login: undefined;
  Assignments: undefined;
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
