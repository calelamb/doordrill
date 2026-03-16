import React from "react";
import { render, screen } from "@testing-library/react-native";

import { ForgotPasswordScreen } from "../screens/ForgotPasswordScreen";
import { LoginScreen } from "../screens/LoginScreen";

jest.mock("expo-blur", () => {
  const React = require("react");
  const { View } = require("react-native");
  return {
    BlurView: ({ children }: { children: React.ReactNode }) => React.createElement(View, null, children),
  };
});

jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return {
    LinearGradient: ({ children }: { children: React.ReactNode }) => React.createElement(View, null, children),
  };
});

jest.mock("lucide-react-native", () => ({
  Lock: () => null,
  Mail: () => null,
  TreePine: () => null,
}));

jest.mock("../services/api", () => ({
  loginWithCredentials: jest.fn(),
  requestPasswordReset: jest.fn(),
  resetPassword: jest.fn(),
}));

jest.mock("../services/notifications", () => ({
  registerPushTokenIfAuthorized: jest.fn(),
}));

jest.mock("../store/session", () => ({
  useSession: () => ({
    setSession: jest.fn(),
  }),
}));

describe("auth screens", () => {
  it("renders forgot password request state", () => {
    render(
      <ForgotPasswordScreen
        navigation={{ navigate: jest.fn(), replace: jest.fn() } as never}
        route={{ key: "ForgotPassword-1", name: "ForgotPassword", params: undefined } as never}
      />
    );

    expect(screen.getByText("Forgot Password")).toBeTruthy();
    expect(screen.getByText("Send Reset Link")).toBeTruthy();
    expect(screen.getByText("Back to Sign In")).toBeTruthy();
  });

  it("renders forgot password reset state from token param", () => {
    render(
      <ForgotPasswordScreen
        navigation={{ navigate: jest.fn(), replace: jest.fn() } as never}
        route={{ key: "ForgotPassword-2", name: "ForgotPassword", params: { token: "reset-token-123" } } as never}
      />
    );

    expect(screen.getAllByText("Set New Password")).toHaveLength(2);
    expect(screen.getByText("Confirm Password")).toBeTruthy();
    expect(screen.getByText("Back to Sign In")).toBeTruthy();
  });

  it("shows forgot password link on login screen", () => {
    render(
      <LoginScreen
        navigation={{ navigate: jest.fn(), setParams: jest.fn() } as never}
        route={{ key: "Login-1", name: "Login", params: undefined } as never}
      />
    );

    expect(screen.getByText("Forgot password?")).toBeTruthy();
  });
});
